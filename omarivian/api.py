"""Minimal, allowlisted client for Rivian's unofficial owner API.

Only authentication mutations are implemented. There is deliberately no generic
public request method and no vehicle-control mutation in this package.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

GATEWAY = "https://rivian.com/api/gql/gateway/graphql"
USER_AGENT = "RivianApp/707 CFNetwork/1237 Darwin/20.4.0"
CLIENT_NAME = "com.rivian.ios.consumer-apollo-ios"

class ApiError(RuntimeError): pass
class AuthenticationError(ApiError): pass
class SchemaError(ApiError): pass


def _is_rivian_https_url(value: str) -> bool:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (hostname == "rivian.com" or hostname.endswith(".rivian.com"))


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
        try:
            # GATEWAY is a module constant; no caller-controlled URL or scheme reaches urllib.
            with urlopen(Request(GATEWAY, data=payload, headers=headers, method="POST"), timeout=self.timeout) as response:  # nosec B310
                body = json.load(response)
        except HTTPError as exc:
            if exc.code in (401, 403): raise AuthenticationError("Rivian sign-in expired") from exc
            raise ApiError(f"Rivian returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ApiError("Could not reach Rivian") from exc
        errors = body.get("errors") or []
        if errors:
            first = errors[0]
            code = (first.get("extensions") or {}).get("code", "")
            reason = (first.get("extensions") or {}).get("reason", "")
            if code == "UNAUTHENTICATED": raise AuthenticationError("Rivian sign-in expired")
            raise ApiError(first.get("message") or reason or code or "Rivian API error")
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
        self.create_session()

    def vehicles(self) -> list[dict[str, Any]]:
        query = "query getUserInfo { currentUser { vehicles { id vin name vehicle { modelYear model } } } }"
        user = self._post("getUserInfo", query, None, authenticated=True).get("currentUser") or {}
        vehicles = user.get("vehicles")
        if not isinstance(vehicles, list): raise SchemaError("Rivian vehicle list response changed")
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
            with urlopen(Request(source_url, headers={"User-Agent": USER_AGENT}), timeout=self.timeout) as response:  # nosec B310
                content_type = response.headers.get_content_type()
                body = response.read(max_bytes + 1)
        except HTTPError as exc:
            raise ApiError(f"Rivian artwork returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ApiError("Could not download Rivian artwork") from exc
        if not content_type.startswith("image/") or len(body) > max_bytes:
            raise ApiError("Rivian artwork response was not a supported image")
        extension = {"image/png": ".png", "image/webp": ".webp", "image/jpeg": ".jpg"}.get(content_type)
        if extension is None:
            raise ApiError("Rivian artwork format was not supported")
        return body, extension

    def vehicle_state(self, vehicle_id: str, include_location: bool) -> dict[str, Any]:
        fields = [
            "cloudConnection { lastSync isOnline }", "powerState { timeStamp value }",
            "batteryLevel { timeStamp value }", "batteryLimit { timeStamp value }",
            "distanceToEmpty { timeStamp value }", "chargerState { timeStamp value }",
            "chargerStatus { timeStamp value }", "chargePortState { timeStamp value }",
            "timeToEndOfCharge { timeStamp value }", "vehicleMileage { timeStamp value }",
            "otaCurrentVersion { timeStamp value }", "cabinClimateInteriorTemperature { timeStamp value }",
            "cabinPreconditioningStatus { timeStamp value }", "cabinPreconditioningType { timeStamp value }",
            "doorFrontLeftClosed { timeStamp value }", "doorFrontRightClosed { timeStamp value }",
            "doorRearLeftClosed { timeStamp value }", "doorRearRightClosed { timeStamp value }",
            "doorFrontLeftLocked { timeStamp value }", "doorFrontRightLocked { timeStamp value }",
            "doorRearLeftLocked { timeStamp value }", "doorRearRightLocked { timeStamp value }",
            "closureFrunkClosed { timeStamp value }", "closureLiftgateClosed { timeStamp value }",
            "closureTailgateClosed { timeStamp value }", "closureTonneauClosed { timeStamp value }",
        ]
        if include_location: fields.append("gnssLocation { timeStamp latitude longitude isAuthorized }")
        query = "query GetVehicleState($vehicleID: String!) { vehicleState(id: $vehicleID) { " + " ".join(fields) + " } }"
        state = self._post("GetVehicleState", query, {"vehicleID": vehicle_id}, authenticated=True).get("vehicleState")
        if not isinstance(state, dict): raise SchemaError("Rivian vehicle state response changed")
        return state
