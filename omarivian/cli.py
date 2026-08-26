"""Command-line helper for the OmaRivian Quickshell plugin."""
from __future__ import annotations

import argparse
import getpass
import json
import math
import sys
import time
from datetime import datetime, timezone
from typing import Any

from .api import ApiError, AuthenticationError, RivianReadClient, SchemaError, Tokens
from .store import (
    cached_artwork,
    clear_local_data,
    command_lock,
    clear_tokens,
    load_tokens,
    read_preferences,
    read_state,
    save_tokens,
    write_artwork,
    write_preferences,
    write_state,
)


class NoLinkedAccount(AuthenticationError):
    """Raised when the user has not linked an account yet."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _record(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else None


def _timestamp(value: Any) -> str | None:
    stamp = value.get("timeStamp") if isinstance(value, dict) else None
    return str(stamp) if stamp else None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _bool_state(value: Any, truthy: set[str]) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in truthy:
        return True
    if text in {"false", "off", "inactive", "closed", "locked", "no", "0"}:
        return False
    return None


def _closed(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "closed", "close", "yes", "1"}:
        return True
    if text in {"false", "open", "ajar", "no", "0"}:
        return False
    return None


def _locked(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "locked", "lock", "yes", "1"}:
        return True
    if text in {"false", "unlocked", "unlock", "no", "0"}:
        return False
    return None


def _latest_timestamp(state: dict[str, Any]) -> str | None:
    stamps = [
        stamp for value in state.values()
        if (stamp := _timestamp(value)) is not None
    ]
    cloud = state.get("cloudConnection") or {}
    if cloud.get("lastSync"):
        stamps.append(str(cloud["lastSync"]))
    return max(stamps) if stamps else None


def normalize_vehicle(summary: dict[str, Any], state: dict[str, Any], include_location: bool) -> dict[str, Any]:
    details = summary.get("vehicle") or {}
    doors = {
        "driver door": _closed(_record(state.get("doorFrontLeftClosed"))),
        "passenger door": _closed(_record(state.get("doorFrontRightClosed"))),
        "left rear door": _closed(_record(state.get("doorRearLeftClosed"))),
        "right rear door": _closed(_record(state.get("doorRearRightClosed"))),
        "front trunk": _closed(_record(state.get("closureFrunkClosed"))),
        "liftgate": _closed(_record(state.get("closureLiftgateClosed"))),
        "tailgate": _closed(_record(state.get("closureTailgateClosed"))),
        "tonneau": _closed(_record(state.get("closureTonneauClosed"))),
    }
    lock_values = [
        _locked(_record(state.get(key)))
        for key in (
            "doorFrontLeftLocked", "doorFrontRightLocked",
            "doorRearLeftLocked", "doorRearRightLocked",
            "closureFrunkLocked", "closureLiftgateLocked",
        )
    ]
    known_locks = [item for item in lock_values if item is not None]
    if known_locks and not all(known_locks):
        security = "unlocked"
    elif len(known_locks) == len(lock_values) and all(known_locks):
        security = "locked"
    else:
        security = "unknown"
    open_closures = [name for name, closed in doors.items() if isinstance(closed, bool) and not closed]

    raw_power_state = str(_record(state.get("powerState")) or "unknown")
    driving = raw_power_state.strip().lower() == "go"
    power_state = "driving" if driving else raw_power_state
    charger = str(_record(state.get("chargerState")) or _record(state.get("chargerStatus")) or "unknown")
    lower_charger = charger.lower()
    charging = "charging" in lower_charger and not any(word in lower_charger for word in ("not", "done", "complete"))
    plugged = charging or any(word in lower_charger for word in ("connected", "plugged", "ready", "complete"))
    minutes_remaining = _number(_record(state.get("timeToEndOfCharge")))
    if driving:
        charger = "not_charging"
        charging = False
        plugged = False
        minutes_remaining = None
    climate_raw = str(_record(state.get("cabinPreconditioningStatus")) or "")
    climate_active = _bool_state(climate_raw, {"on", "active", "running", "preconditioning"})
    if climate_active is None:
        climate_active = False

    location = None
    location_record = state.get("gnssLocation") or {}
    location_authorized = location_record.get("isAuthorized", True)
    if include_location and not (isinstance(location_authorized, bool) and not location_authorized):
        latitude = _number(location_record.get("latitude"))
        longitude = _number(location_record.get("longitude"))
        if latitude is not None and longitude is not None:
            location = {"latitude": latitude, "longitude": longitude, "reportedAt": _timestamp(location_record)}

    distance_km = _number(_record(state.get("distanceToEmpty")))
    odometer_m = _number(_record(state.get("vehicleMileage")))
    return {
        "id": str(summary.get("id") or ""),
        "name": str(summary.get("name") or details.get("model") or "Rivian"),
        "model": str(details.get("model") or "Rivian"),
        "modelYear": details.get("modelYear"),
        "vinSuffix": str(summary.get("vin") or "")[-6:],
        "reportedAt": _latest_timestamp(state),
        "online": (state.get("cloudConnection") or {}).get("isOnline"),
        "powerState": power_state,
        "battery": {
            "percent": _number(_record(state.get("batteryLevel"))),
            "limitPercent": _number(_record(state.get("batteryLimit"))),
            "rangeKm": distance_km,
        },
        "charging": {
            "state": charger,
            "charging": charging,
            "pluggedIn": plugged,
            "minutesRemaining": minutes_remaining,
        },
        "security": {"state": security, "openClosures": open_closures},
        "climate": {
            "cabinC": _number(_record(state.get("cabinClimateInteriorTemperature"))),
            "targetC": _number(_record(state.get("cabinClimateDriverTemperature"))),
            "active": climate_active,
            "mode": str(_record(state.get("cabinPreconditioningType")) or ""),
        },
        "location": location,
        "odometerKm": odometer_m / 1000 if odometer_m is not None else None,
        "softwareVersion": str(_record(state.get("otaCurrentVersion")) or ""),
        "lastConnection": str((state.get("cloudConnection") or {}).get("lastSync") or ""),
    }


def _load_client() -> RivianReadClient:
    raw = load_tokens()
    if not raw:
        raise NoLinkedAccount("No Rivian account is linked")
    return RivianReadClient(Tokens.from_json(raw))


def _write_error(status: str, message: str) -> None:
    previous = read_state()
    previous.update({"schemaVersion": 1, "status": status, "message": message, "polledAt": _now()})
    write_state(previous)


def _prompt_for_password() -> str:
    return getpass.getpass("Rivian password: ")


def command_link(_: argparse.Namespace) -> int:
    print("OmaRivian account linking\n")
    print("Unofficial integration: not affiliated with Rivian. The session token may carry")
    print("vehicle-control authority even though OmaRivian implements read-only queries.")
    print("Your password is sent only to Rivian and is never saved. Tokens go to Secret Service.\n")
    email = input("Rivian email: ").strip()
    password = _prompt_for_password()
    client = RivianReadClient()
    try:
        otp_required = client.login(email, password)
        if otp_required:
            code = input("One-time code: ").strip()
            client.verify_otp(email, code)
        vehicles = client.vehicles()
        if not vehicles:
            raise ApiError("No vehicles are associated with this account")
        with command_lock():
            save_tokens(client.tokens.to_json())
            prefs = read_preferences()
            if not prefs.get("selectedVehicleId"):
                prefs["selectedVehicleId"] = str(vehicles[0].get("id") or "")
                write_preferences(prefs)
            print(f"\nLinked {len(vehicles)} vehicle{'s' if len(vehicles) != 1 else ''}. Refreshing status…")
            return command_refresh(argparse.Namespace(location=None, location_generation=None, vehicle=None))
    except (ApiError, RuntimeError) as exc:
        with command_lock():
            _write_error("unlinked", str(exc))
        print(f"Link failed: {exc}", file=sys.stderr)
        return 1


def command_refresh(args: argparse.Namespace) -> int:
    prefs = read_preferences()
    generation = getattr(args, "location_generation", None)
    if generation is not None:
        try:
            previous_generation = int(prefs.get("locationGeneration", 0) or 0)
        except (TypeError, ValueError):
            previous_generation = 0
        if generation < previous_generation:
            return 0
        if generation == previous_generation and bool(args.location) and not bool(prefs.get("locationEnabled")):
            return 0
        prefs["locationGeneration"] = generation
    include_location = bool(prefs.get("locationEnabled", False)) if args.location is None else args.location
    prefs["locationEnabled"] = include_location
    if args.vehicle:
        prefs["selectedVehicleId"] = args.vehicle
    write_preferences(prefs)
    if not include_location:
        sanitized = read_state()
        for cached in sanitized.get("vehicles", []):
            if isinstance(cached, dict):
                cached["location"] = None
        sanitized["locationEnabled"] = False
        write_state(sanitized)
    try:
        client = _load_client()
        try:
            vehicles = client.vehicles()
        except AuthenticationError:
            client.refresh_session()
            # Refresh tokens rotate. Persist the replacement before any later
            # API work can fail, or the next poll may reuse an invalidated token.
            save_tokens(client.tokens.to_json())
            vehicles = client.vehicles()
        selected = str(prefs.get("selectedVehicleId") or "")
        if not any(str(v.get("id")) == selected for v in vehicles):
            selected = str(vehicles[0].get("id") or "") if vehicles else ""
            prefs["selectedVehicleId"] = selected
            write_preferences(prefs)
        prior = {str(v.get("id")): v for v in read_state().get("vehicles", []) if isinstance(v, dict)}
        if not include_location:
            for cached in prior.values():
                cached["location"] = None
        artwork_urls: dict[str, str] = {}
        try:
            artwork_urls = client.vehicle_artwork({str(v.get("id") or "") for v in vehicles})
        except ApiError:
            # Artwork is optional; telemetry remains useful when its CDN or
            # manifest is temporarily unavailable.
            artwork_urls = {}
        normalized = []
        for vehicle in vehicles:
            vehicle_id = str(vehicle.get("id") or "")
            prior_item = prior.get(vehicle_id) or {}
            prior_artwork = prior_item.get("artwork")
            if vehicle_id == selected:
                item = normalize_vehicle(vehicle, client.vehicle_state(vehicle_id, include_location), include_location)
            else:
                item = prior_item or normalize_vehicle(vehicle, {}, False)
            item["artwork"] = prior_artwork
            source_url = artwork_urls.get(vehicle_id)
            if source_url:
                try:
                    path = cached_artwork(vehicle_id, source_url)
                    if path is None:
                        body, extension = client.download_artwork(source_url)
                        path = write_artwork(vehicle_id, source_url, body, extension)
                    item["artwork"] = path.as_uri()
                except (ApiError, OSError):
                    # Keep the last working local render; telemetry refresh is
                    # independent from this optional visual asset.
                    item["artwork"] = prior_artwork
            normalized.append(item)
        save_tokens(client.tokens.to_json())
        write_state({"schemaVersion": 1, "status": "linked", "message": "", "polledAt": _now(), "selectedVehicleId": selected, "locationEnabled": include_location, "vehicles": normalized})
        return 0
    except NoLinkedAccount as exc:
        _write_error("unlinked", str(exc)); return 2
    except AuthenticationError as exc:
        _write_error("auth-expired", str(exc)); return 2
    except SchemaError as exc:
        _write_error("schema-error", str(exc)); return 3
    except (ApiError, RuntimeError) as exc:
        _write_error("unavailable", str(exc)); return 1


def command_select(args: argparse.Namespace) -> int:
    prefs = read_preferences(); prefs["selectedVehicleId"] = args.vehicle; write_preferences(prefs)
    return command_refresh(argparse.Namespace(location=None, location_generation=None, vehicle=args.vehicle))


def command_unlink(_: argparse.Namespace) -> int:
    clear_tokens()
    clear_local_data()
    write_state({"schemaVersion": 1, "status": "unlinked", "message": "", "polledAt": _now(), "locationEnabled": False, "vehicles": []})
    return 0


def command_status(_: argparse.Namespace) -> int:
    print(json.dumps(read_state(), indent=2)); return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Read-only Rivian status helper")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("link", help="Link a Rivian account interactively").set_defaults(func=command_link)
    refresh = commands.add_parser("refresh", help="Refresh selected vehicle status")
    location = refresh.add_mutually_exclusive_group()
    location.add_argument("--location", action="store_true", dest="location", default=None, help="Include current coordinates in local state")
    location.add_argument("--no-location", action="store_false", dest="location", help="Remove coordinates from local state")
    refresh.add_argument("--location-generation", type=int, help=argparse.SUPPRESS)
    refresh.add_argument("--vehicle")
    refresh.set_defaults(func=command_refresh)
    select = commands.add_parser("select", help="Select and refresh a vehicle")
    select.add_argument("vehicle")
    select.set_defaults(func=command_select)
    commands.add_parser("unlink", help="Delete account tokens from Secret Service").set_defaults(func=command_unlink)
    commands.add_parser("status", help="Print sanitized widget state").set_defaults(func=command_status)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "status":
        raise SystemExit(args.func(args))
    if args.command == "link":
        raise SystemExit(args.func(args))
    if args.command == "refresh" and args.location is not None and args.location_generation is None:
        args.location_generation = time.time_ns() // 1_000_000
    with command_lock():
        raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
