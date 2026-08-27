"""Minimal, allowlisted client for Rivian's unofficial owner API.

Only authentication mutations are implemented. There is deliberately no generic
public request method and no vehicle-control mutation in this package.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .parallax import ParallaxAuthenticationError, ParallaxError, snapshot as parallax_snapshot

GATEWAY = "https://rivian.com/api/gql/gateway/graphql"
USER_AGENT = "RivianApp/707 CFNetwork/1237 Darwin/20.4.0"
CLIENT_NAME = "com.rivian.ios.consumer-apollo-ios"
MAX_GRAPHQL_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_VEHICLES = 32
_READ_CHUNK_BYTES = 64 * 1024


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


_NO_REDIRECT_OPENER = build_opener(_NoRedirectHandler())


class ApiError(RuntimeError): pass
class AuthenticationError(ApiError): pass
class SchemaError(ApiError): pass


def _is_rivian_https_url(value: str) -> bool:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (hostname == "rivian.com" or hostname.endswith(".rivian.com"))


def _origin(value: str) -> tuple[str, str, int | None]:
    parsed = urlparse(value)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port


def _set_response_timeout(response: Any, timeout: float) -> None:
    """Apply a remaining deadline to urllib's underlying socket when available."""
    stream = getattr(response, "fp", None)
    raw = getattr(stream, "raw", None)
    sock = getattr(raw, "_sock", None)
    if sock is not None:
        sock.settimeout(timeout)


def _read_capped(
    response: Any, max_bytes: int, description: str, *, timeout: float | None = None
) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise ApiError(f"{description} was too large")
        except ValueError:
            content_length = None
    chunks = []
    total = 0
    deadline = time.monotonic() + timeout if timeout is not None else None
    while total <= max_bytes:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ApiError(f"{description} timed out")
            _set_response_timeout(response, remaining)
        chunk = response.read1(min(_READ_CHUNK_BYTES, max_bytes + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if total > max_bytes:
        raise ApiError(f"{description} was too large")
    return b"".join(chunks)


@dataclass
class Tokens:
    access_token: str = field(default_factory=str)
    refresh_token: str = field(default_factory=str)
    user_session_token: str = field(default_factory=str)
    app_session_token: str = field(default_factory=str)
    csrf_token: str = field(default_factory=str)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> "Tokens":
        try:
            data = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise AuthenticationError("Stored Rivian session is invalid; relink the account") from exc
        if not isinstance(data, dict):
            raise AuthenticationError("Stored Rivian session is invalid; relink the account")
        return cls(**{key: str(data.get(key, "")) for key in cls.__dataclass_fields__})

class RivianReadClient:
    def __init__(self, tokens: Tokens | None = None, timeout: int = 15):
        self.tokens = tokens or Tokens()
        self.timeout = timeout
        self.otp_token = ""

    def _post(self, operation: str, query: str, variables: dict[str, Any] | None = None, *, authenticated: bool = False) -> dict[str, Any]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Apollographql-Client-Name": CLIENT_NAME,
            "dc-cid": f"m-ios-{uuid.uuid4()}",
        }
        if self.tokens.app_session_token: headers["A-Sess"] = self.tokens.app_session_token
        if self.tokens.csrf_token: headers["Csrf-Token"] = self.tokens.csrf_token
        if authenticated:
            headers["U-Sess"] = self.tokens.user_session_token
            headers["Authorization"] = f"Bearer {self.tokens.access_token}"
        payload = json.dumps({"operationName": operation, "query": query, "variables": variables}).encode()
        http_error_code: int | None = None
        try:
            # GATEWAY is fixed in production, redirects are rejected, and the final
            # response origin is checked before any authenticated body is read.
            request = Request(GATEWAY, data=payload, headers=headers, method="POST")
            with _NO_REDIRECT_OPENER.open(request, timeout=self.timeout) as response:  # nosec B310
                if _origin(response.geturl()) != _origin(GATEWAY):
                    raise ApiError("Rivian response changed origin")
                raw = _read_capped(
                    response,
                    MAX_GRAPHQL_RESPONSE_BYTES,
                    "Rivian response",
                    timeout=float(self.timeout),
                )
        except HTTPError as exc:
            code = exc.code
            if code in (401, 403):
                exc.close()
                raise AuthenticationError("Rivian sign-in expired") from exc
            if code != 400:
                exc.close()
                raise ApiError(f"Rivian returned HTTP {code}") from exc
            # Rivian returns expired-session GraphQL errors with HTTP 400. Read
            # this body under the same limits as a successful response so the
            # caller can renew the session instead of requiring another link.
            try:
                raw = _read_capped(
                    exc,
                    MAX_GRAPHQL_RESPONSE_BYTES,
                    "Rivian response",
                    timeout=float(self.timeout),
                )
            except (URLError, TimeoutError, OSError) as read_exc:
                raise ApiError("Could not reach Rivian") from read_exc
            finally:
                exc.close()
            http_error_code = code
        except (URLError, TimeoutError, OSError) as exc:
            raise ApiError("Could not reach Rivian") from exc
        try:
            body = json.loads(raw)
        except (TypeError, ValueError) as exc:
            if http_error_code is not None:
                raise ApiError(f"Rivian returned HTTP {http_error_code}") from exc
            raise SchemaError("Rivian response was not valid JSON") from exc
        if not isinstance(body, dict):
            if http_error_code is not None:
                raise ApiError(f"Rivian returned HTTP {http_error_code}")
            raise SchemaError("Rivian response was not a JSON object")
        errors = body.get("errors", [])
        if errors is None:
            errors = []
        if not isinstance(errors, list):
            if http_error_code is not None:
                raise ApiError(f"Rivian returned HTTP {http_error_code}")
            raise SchemaError("Rivian response contained malformed errors")
        if errors:
            authenticated_error = any(
                isinstance(error, dict)
                and isinstance(error.get("extensions"), dict)
                and str(error["extensions"].get("code") or "") == "UNAUTHENTICATED"
                for error in errors
            )
            if authenticated_error:
                raise AuthenticationError("Rivian sign-in expired")
            for error in errors:
                if not isinstance(error, dict):
                    if http_error_code is not None:
                        raise ApiError(f"Rivian returned HTTP {http_error_code}")
                    raise SchemaError("Rivian response contained malformed errors")
                extensions = error.get("extensions")
                if extensions is not None and not isinstance(extensions, dict):
                    if http_error_code is not None:
                        raise ApiError(f"Rivian returned HTTP {http_error_code}")
                    raise SchemaError("Rivian response contained malformed errors")
            if http_error_code is not None:
                raise ApiError(f"Rivian returned HTTP {http_error_code}")
            # Upstream messages can contain account or request context. Keep
            # them out of state.json and the QML error surface.
            raise ApiError("Rivian API error")
        if http_error_code is not None:
            raise ApiError(f"Rivian returned HTTP {http_error_code}")
        data = body.get("data")
        if not isinstance(data, dict): raise SchemaError("Rivian response did not contain data")
        return data

    def create_session(self) -> None:
        data = self._post("CreateCSRFToken", "mutation CreateCSRFToken { createCsrfToken { csrfToken appSessionToken } }", None)
        session = data.get("createCsrfToken") or {}
        self.tokens.csrf_token = str(session.get("csrfToken") or "")
        self.tokens.app_session_token = str(session.get("appSessionToken") or "")
        if not self.tokens.csrf_token or not self.tokens.app_session_token: raise SchemaError("Rivian session response changed")

    def login(self, email: str, password: str) -> bool:
        self.create_session()
        query = "mutation Login($email: String!, $password: String!) { login(email: $email, password: $password) { __typename ... on MobileLoginResponse { accessToken refreshToken userSessionToken } ... on MobileMFALoginResponse { otpToken } } }"
        login = self._post("Login", query, {"email": email, "password": password}).get("login") or {}
        if login.get("otpToken"):
            self.otp_token = str(login["otpToken"])
            return True
        self._adopt_login(login)
        return False

    def verify_otp(self, email: str, code: str) -> None:
        query = "mutation LoginWithOTP($email: String!, $otpCode: String!, $otpToken: String!) { loginWithOTP(email: $email, otpCode: $otpCode, otpToken: $otpToken) { accessToken refreshToken userSessionToken } }"
        login = self._post("LoginWithOTP", query, {"email": email, "otpCode": code, "otpToken": self.otp_token}).get("loginWithOTP") or {}
        self._adopt_login(login)

    def _adopt_login(self, payload: dict[str, Any]) -> None:
        self.tokens.access_token = str(payload.get("accessToken") or "")
        self.tokens.refresh_token = str(payload.get("refreshToken") or "")
        self.tokens.user_session_token = str(payload.get("userSessionToken") or "")
        if not self.tokens.access_token or not self.tokens.user_session_token: raise AuthenticationError("Rivian sign-in did not return a usable session")

    def refresh_session(self) -> None:
        refresh_token = self.tokens.refresh_token
        if not refresh_token:
            raise AuthenticationError("Rivian sign-in cannot be renewed; relink the account")
        self.create_session()
        query = "mutation RefreshAccessToken($refreshToken: String!) { refreshAccessToken(refreshToken: $refreshToken) { accessToken refreshToken } }"
        payload = self._post(
            "RefreshAccessToken",
            query,
            {"refreshToken": refresh_token},
        ).get("refreshAccessToken") or {}
        if not isinstance(payload, dict):
            raise AuthenticationError("Rivian sign-in could not be renewed; relink the account")
        access_token = str(payload.get("accessToken") or "")
        rotated_refresh_token = str(payload.get("refreshToken") or "")
        if not access_token or not rotated_refresh_token:
            raise AuthenticationError("Rivian sign-in could not be renewed; relink the account")
        self.tokens.access_token = access_token
        self.tokens.refresh_token = rotated_refresh_token
        # RefreshAccessToken does not return a userSessionToken. Preserve the
        # distinct U-Sess established by login; replacing it with accessToken
        # makes GraphQL requests work but causes Parallax to close with 4403.

    def vehicles(self) -> list[dict[str, Any]]:
        query = "query getUserInfo { currentUser { vehicles { id vin name vehicle { modelYear model } } } }"
        user = self._post("getUserInfo", query, None, authenticated=True).get("currentUser")
        if not isinstance(user, dict):
            raise SchemaError("Rivian vehicle list response changed")
        vehicles = user.get("vehicles")
        if not isinstance(vehicles, list) or not all(isinstance(item, dict) for item in vehicles):
            raise SchemaError("Rivian vehicle list response changed")
        if len(vehicles) > MAX_VEHICLES:
            raise SchemaError("Rivian returned too many vehicles")
        return vehicles

    def vehicle_artwork(self, vehicle_ids: set[str]) -> dict[str, str]:
        """Return the best configured artwork URL for each requested vehicle.

        Rivian's version 3 feed is the cel artwork used by the owner app. The
        feed already reflects model, paint, wheels, and other configuration.
        """
        query = "query getVehicleImages($extension: String, $resolution: String, $versionForVehicle: String, $versionForPreOrder: String) { getVehicleOrderMobileImages(resolution: $resolution, extension: $extension, version: $versionForPreOrder) { ...image } getVehicleMobileImages(resolution: $resolution, extension: $extension, version: $versionForVehicle) { ...image } } fragment image on VehicleMobileImage { orderId vehicleId url extension resolution size design placement overlays { url overlay zIndex } }"
        data = self._post("getVehicleImages", query, {
            "extension": None,
            "resolution": "@3x",
            "versionForVehicle": "3",
            "versionForPreOrder": "3",
        }, authenticated=True)
        rows = data.get("getVehicleMobileImages")
        if not isinstance(rows, list):
            raise SchemaError("Rivian vehicle artwork response changed")
        selected: dict[str, tuple[int, str]] = {}
        placement_rank = {"side": 4, "three-quarter": 3, "front": 2, "rear": 1}
        for row in rows:
            if not isinstance(row, dict):
                continue
            vehicle_id = str(row.get("vehicleId") or "")
            source_url = str(row.get("url") or "")
            if vehicle_id not in vehicle_ids or not _is_rivian_https_url(source_url):
                continue
            score = placement_rank.get(str(row.get("placement") or ""), 0) * 10
            score += 4 if row.get("size") == "large" else 0
            score += 2 if row.get("design") == "dark" else 0
            score += 1 if row.get("resolution") == "@3x" else 0
            if score > selected.get(vehicle_id, (-1, ""))[0]:
                selected[vehicle_id] = (score, source_url)
        return {vehicle_id: value[1] for vehicle_id, value in selected.items()}

    def download_artwork(self, source_url: str, max_bytes: int = 12 * 1024 * 1024) -> tuple[bytes, str]:
        if not _is_rivian_https_url(source_url):
            raise ApiError("Rivian artwork URL was not secure")
        try:
            request = Request(source_url, headers={"User-Agent": USER_AGENT})
            with _NO_REDIRECT_OPENER.open(request, timeout=self.timeout) as response:  # nosec B310
                if not _is_rivian_https_url(response.geturl()):
                    raise ApiError("Rivian artwork response changed origin")
                content_type = response.headers.get_content_type()
                body = _read_capped(
                    response, max_bytes, "Rivian artwork response", timeout=float(self.timeout)
                )
        except HTTPError as exc:
            code = exc.code
            exc.close()
            raise ApiError(f"Rivian artwork returned HTTP {code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ApiError("Could not download Rivian artwork") from exc
        if not content_type.startswith("image/") or len(body) > max_bytes:
            raise ApiError("Rivian artwork response was not a supported image")
        extension = {"image/png": ".png", "image/webp": ".webp", "image/jpeg": ".jpg"}.get(content_type)
        if extension is None:
            raise ApiError("Rivian artwork format was not supported")
        return body, extension

    def parallax_state(self, vehicle_id: str, topics: set[str]) -> dict[str, Any]:
        try:
            return parallax_snapshot(
                vehicle_id,
                topics,
                app_session_token=self.tokens.app_session_token,
                user_session_token=self.tokens.user_session_token,
                csrf_token=self.tokens.csrf_token,
                timeout=min(float(self.timeout), 8.0),
            )
        except ParallaxAuthenticationError as exc:
            raise AuthenticationError("Rivian sign-in expired") from exc
        except (ParallaxError, OSError, TimeoutError):
            # Newer telemetry is a compatibility fallback. A bounded failure must
            # not discard otherwise useful legacy state from an R1 or R2.
            return {}

    def vehicle_state(self, vehicle_id: str, include_location: bool) -> dict[str, Any]:
        fields = [
            "cloudConnection { lastSync isOnline }", "powerState { timeStamp value }",
            "batteryLevel { timeStamp value }", "batteryLimit { timeStamp value }",
            "distanceToEmpty { timeStamp value }", "chargerState { timeStamp value }",
            "chargerStatus { timeStamp value }", "chargePortState { timeStamp value }",
            "timeToEndOfCharge { timeStamp value }", "vehicleMileage { timeStamp value }",
            "otaCurrentVersion { timeStamp value }", "cabinClimateInteriorTemperature { timeStamp value }",
            "cabinClimateDriverTemperature { timeStamp value }",
            "cabinPreconditioningStatus { timeStamp value }", "cabinPreconditioningType { timeStamp value }",
            "doorFrontLeftClosed { timeStamp value }", "doorFrontRightClosed { timeStamp value }",
            "doorRearLeftClosed { timeStamp value }", "doorRearRightClosed { timeStamp value }",
            "doorFrontLeftLocked { timeStamp value }", "doorFrontRightLocked { timeStamp value }",
            "doorRearLeftLocked { timeStamp value }", "doorRearRightLocked { timeStamp value }",
            "closureFrunkClosed { timeStamp value }", "closureLiftgateClosed { timeStamp value }",
            "closureFrunkLocked { timeStamp value }", "closureLiftgateLocked { timeStamp value }",
            "closureTailgateClosed { timeStamp value }", "closureTonneauClosed { timeStamp value }",
        ]
        query = "query GetVehicleState($vehicleID: String!) { vehicleState(id: $vehicleID) { " + " ".join(fields) + " } }"
        state = self._post("GetVehicleState", query, {"vehicleID": vehicle_id}, authenticated=True).get("vehicleState")
        if not isinstance(state, dict): raise SchemaError("Rivian vehicle state response changed")

        # Keep optional GNSS isolated: R1 can still use the legacy field, while
        # R2 may reject that field entirely and continue through Parallax.
        if include_location:
            location_query = (
                "query GetVehicleLocation($vehicleID: String!) { vehicleState(id: $vehicleID) { "
                "gnssLocation { timeStamp latitude longitude isAuthorized } } }"
            )
            try:
                location_state = self._post(
                    "GetVehicleLocation",
                    location_query,
                    {"vehicleID": vehicle_id},
                    authenticated=True,
                ).get("vehicleState")
            except ApiError as exc:
                if isinstance(exc, AuthenticationError):
                    raise
                # A missing/retired legacy GNSS field is expected on newer
                # vehicles; the allowlisted Parallax fallback below handles it.
                location_state = None
            if isinstance(location_state, dict):
                state["gnssLocation"] = location_state.get("gnssLocation")

        def has_record(key: str) -> bool:
            value = state.get(key)
            return isinstance(value, dict) and value.get("value") is not None

        lock_fields = {
            "doorFrontLeftLocked", "doorFrontRightLocked",
            "doorRearLeftLocked", "doorRearRightLocked",
            "closureFrunkLocked", "closureLiftgateLocked",
        }
        closure_fields = {
            "doorFrontLeftClosed", "doorFrontRightClosed",
            "doorRearLeftClosed", "doorRearRightClosed",
            "closureFrunkClosed", "closureLiftgateClosed",
        }
        topics: set[str] = set()
        if any(not has_record(key) for key in lock_fields):
            topics.add("body.locks.states")
        if any(not has_record(key) for key in closure_fields):
            topics.add("body.closures.states")
        power_record = state.get("powerState")
        power_value = power_record.get("value") if isinstance(power_record, dict) else None
        if not isinstance(power_value, str) or power_value.strip().lower() in {"", "unknown"}:
            topics.add("vehicle.power.state")
        if not has_record("cabinClimateInteriorTemperature"):
            topics.add("comfort.cabin.cabin_temperatures")
        if not has_record("cabinClimateDriverTemperature"):
            topics.add("comfort.cabin.hvac_settings_status")
        if not has_record("cabinPreconditioningStatus") or not has_record("cabinPreconditioningType"):
            topics.add("comfort.cabin.cabin_preconditioning_status")
        location = state.get("gnssLocation")
        if include_location and not (
            isinstance(location, dict)
            and isinstance(location.get("latitude"), (int, float))
            and isinstance(location.get("longitude"), (int, float))
        ):
            topics.add("dynamics.vehicle.gnss")

        if topics:
            fallback = self.parallax_state(vehicle_id, topics)
            for key, value in fallback.items():
                current = state.get(key)
                current_value = current.get("value") if isinstance(current, dict) else None
                if current is None or current_value is None or (
                    isinstance(current_value, str) and current_value.strip().lower() == "unknown"
                ):
                    state[key] = value
        return state
