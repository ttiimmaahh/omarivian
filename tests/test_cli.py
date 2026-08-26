import json
import math
import unittest
from typing import Any

from omarivian.api import ApiError, AuthenticationError, RivianReadClient, Tokens
from omarivian.cli import normalize_vehicle


def record(value, timestamp="2026-08-25T12:00:00Z"):
    return {"value": value, "timeStamp": timestamp}


class CliTests(unittest.TestCase):
    def test_tokens_reject_invalid_json(self):
        with self.assertRaises(AuthenticationError):
            Tokens.from_json("not-json")

    def test_normalize_vehicle_converts_units_and_strips_identity(self):
        vehicle = normalize_vehicle(
            {"id": "vehicle-1", "vin": "7FCTGAAA1NN012345", "name": "Adventure", "vehicle": {"model": "R1T", "modelYear": 2024}},
            {
                "batteryLevel": record(72.4),
                "batteryLimit": record(80),
                "distanceToEmpty": record(400),
                "vehicleMileage": record(160934),
                "doorFrontLeftLocked": record("locked"),
                "doorFrontRightLocked": record("locked"),
                "doorRearLeftLocked": record("locked"),
                "doorRearRightLocked": record("locked"),
                "closureFrunkLocked": record("locked"),
                "closureLiftgateLocked": record("locked"),
                "closureFrunkClosed": record("open"),
                "chargerState": record("charging"),
                "cabinClimateInteriorTemperature": record(21.5),
                "gnssLocation": {"latitude": 30.2672, "longitude": -97.7431, "timeStamp": "2026-08-25T12:01:00Z", "isAuthorized": True},
                "cloudConnection": {"isOnline": True, "lastSync": "2026-08-25T12:02:00Z"},
            },
            True,
        )
        self.assertEqual(vehicle["vinSuffix"], "012345")
        self.assertNotIn("vin", vehicle)
        self.assertEqual(vehicle["security"], {"state": "locked", "openClosures": ["front trunk"]})
        self.assertTrue(vehicle["charging"]["charging"])
        self.assertTrue(math.isclose(vehicle["odometerKm"], 160.934))
        self.assertEqual(vehicle["location"]["latitude"], 30.2672)
        self.assertEqual(vehicle["reportedAt"], "2026-08-25T12:02:00Z")

    def test_vehicle_state_uses_parallax_when_legacy_security_is_missing(self):
        client = RivianReadClient()
        client._post = lambda *args, **kwargs: {
            "vehicleState": {
                "doorFrontLeftLocked": None,
                "doorFrontRightLocked": None,
                "doorRearLeftLocked": None,
                "doorRearRightLocked": None,
                "closureFrunkClosed": None,
                "closureLiftgateClosed": None,
            }
        }
        requested = []

        def parallax_state(vehicle_id, topics):
            requested.append((vehicle_id, set(topics)))
            return {
                "doorFrontLeftLocked": record("locked"),
                "doorFrontRightLocked": record("locked"),
                "doorRearLeftLocked": record("locked"),
                "doorRearRightLocked": record("locked"),
                "closureFrunkLocked": record("locked"),
                "closureLiftgateLocked": record("locked"),
                "closureFrunkClosed": record("closed"),
                "closureLiftgateClosed": record("closed"),
                "powerState": record("sleeping"),
            }

        setattr(client, "parallax_state", parallax_state)
        state = client.vehicle_state("vehicle-1", False)

        self.assertEqual(state["doorFrontLeftLocked"]["value"], "locked")
        self.assertEqual(state["closureLiftgateClosed"]["value"], "closed")
        self.assertEqual(
            requested,
            [("vehicle-1", {"body.locks.states", "body.closures.states", "vehicle.power.state"})],
        )

    def test_vehicle_state_keeps_complete_legacy_r1_state(self):
        complete = {
            key: record(value)
            for key, value in {
                "doorFrontLeftLocked": "locked", "doorFrontRightLocked": "locked",
                "doorRearLeftLocked": "locked", "doorRearRightLocked": "locked",
                "closureFrunkLocked": "locked", "closureLiftgateLocked": "locked",
                "doorFrontLeftClosed": "closed", "doorFrontRightClosed": "closed",
                "doorRearLeftClosed": "closed", "doorRearRightClosed": "closed",
                "closureFrunkClosed": "closed", "closureLiftgateClosed": "closed",
                "powerState": "sleeping",
            }.items()
        }
        client = RivianReadClient()
        client._post = lambda *args, **kwargs: {"vehicleState": complete.copy()}

        def unexpected_parallax(_vehicle_id, _topics):
            self.fail("complete legacy R1 state should not use Parallax")

        setattr(client, "parallax_state", unexpected_parallax)
        state = client.vehicle_state("vehicle-1", False)
        self.assertEqual(state["doorFrontLeftLocked"]["value"], "locked")

    def test_vehicle_state_requests_parallax_gnss_only_with_opt_in(self):
        complete_security: dict[str, Any] = {
            key: record("locked" if "Locked" in key else "closed")
            for key in (
                "doorFrontLeftLocked", "doorFrontRightLocked",
                "doorRearLeftLocked", "doorRearRightLocked",
                "closureFrunkLocked", "closureLiftgateLocked",
                "doorFrontLeftClosed", "doorFrontRightClosed",
                "doorRearLeftClosed", "doorRearRightClosed",
                "closureFrunkClosed", "closureLiftgateClosed",
            )
        }
        complete_security["powerState"] = record("sleeping")
        complete_security["gnssLocation"] = None
        client = RivianReadClient()

        def post(
            operation: str,
            query: str,
            variables: dict[str, Any] | None = None,
            *,
            authenticated: bool = False,
        ) -> dict[str, Any]:
            del operation, variables, authenticated
            if "gnssLocation" in query:
                raise ApiError("legacy GNSS is unavailable for this vehicle")
            return {"vehicleState": complete_security.copy()}

        client._post = post
        requested = []

        def parallax_state(_vehicle_id, topics):
            requested.append(set(topics))
            return {"gnssLocation": {"latitude": 35.0, "longitude": -80.0}}

        setattr(client, "parallax_state", parallax_state)
        without_location = client.vehicle_state("vehicle-1", False)
        with_location = client.vehicle_state("vehicle-1", True)

        self.assertIsNone(without_location["gnssLocation"])
        self.assertEqual(with_location["gnssLocation"]["latitude"], 35.0)
        self.assertEqual(requested, [{"dynamics.vehicle.gnss"}])

    def test_normalize_vehicle_keeps_partial_locked_telemetry_unknown(self):
        vehicle = normalize_vehicle(
            {"id": "vehicle-1"},
            {"doorFrontLeftLocked": record("locked")},
            False,
        )
        self.assertEqual(vehicle["security"]["state"], "unknown")

    def test_normalize_vehicle_reports_any_known_unlocked_lock(self):
        vehicle = normalize_vehicle(
            {"id": "vehicle-1"},
            {"doorFrontLeftLocked": record("unlocked")},
            False,
        )
        self.assertEqual(vehicle["security"]["state"], "unlocked")

    def test_normalize_vehicle_includes_closure_locks_in_security(self):
        state = {
            "doorFrontLeftLocked": record("locked"),
            "doorFrontRightLocked": record("locked"),
            "doorRearLeftLocked": record("locked"),
            "doorRearRightLocked": record("locked"),
            "closureFrunkLocked": record("unlocked"),
            "closureLiftgateLocked": record("locked"),
        }
        vehicle = normalize_vehicle({"id": "vehicle-1"}, state, False)
        self.assertEqual(vehicle["security"]["state"], "unlocked")

    def test_vehicle_artwork_prefers_large_dark_side_render(self):
        client = RivianReadClient()
        client._post = lambda *args, **kwargs: {
            "getVehicleMobileImages": [
                {"vehicleId": "vehicle-1", "url": "https://media.rivian.com/front.png", "placement": "front", "size": "large", "design": "dark", "resolution": "@3x"},
                {"vehicleId": "vehicle-1", "url": "https://media.rivian.com/side-light.png", "placement": "side", "size": "large", "design": "light", "resolution": "@3x"},
                {"vehicleId": "vehicle-1", "url": "https://media.rivian.com/side-dark.png", "placement": "side", "size": "large", "design": "dark", "resolution": "@3x"},
                {"vehicleId": "other", "url": "https://media.rivian.com/other.png", "placement": "side", "size": "large", "design": "dark", "resolution": "@3x"},
            ]
        }
        self.assertEqual(
            client.vehicle_artwork({"vehicle-1"}),
            {"vehicle-1": "https://media.rivian.com/side-dark.png"},
        )

    def test_location_is_not_written_without_opt_in(self):
        vehicle = normalize_vehicle(
            {"id": "vehicle-1", "vin": "123456"},
            {"gnssLocation": {"latitude": 1.2, "longitude": 3.4, "isAuthorized": True}},
            False,
        )
        self.assertIsNone(vehicle["location"])
        self.assertNotIn("1.2", json.dumps(vehicle))


if __name__ == "__main__":
    unittest.main()
