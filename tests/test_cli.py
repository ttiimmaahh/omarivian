import json
import math
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import omarivian.store as store
from omarivian.api import MAX_VEHICLES, ApiError, AuthenticationError, RivianReadClient, Tokens
from omarivian.cli import MAX_TEXT_CHARS, normalize_vehicle


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
                "chargerState": record("charging_active"),
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

    def test_normalize_vehicle_bounds_api_supplied_strings(self):
        huge = "A" * 5000
        vehicle = normalize_vehicle(
            {"id": huge, "vin": huge, "name": huge, "vehicle": {"model": huge, "modelYear": huge}},
            {
                "powerState": record(huge),
                "chargerState": record(huge),
                "cabinPreconditioningType": record(huge),
                "otaCurrentVersion": record(huge),
                "cloudConnection": {"isOnline": huge, "lastSync": huge},
            },
            False,
        )
        bounded = (
            vehicle["id"], vehicle["name"], vehicle["model"], vehicle["powerState"],
            vehicle["softwareVersion"], vehicle["lastConnection"], vehicle["reportedAt"],
            vehicle["charging"]["state"], vehicle["climate"]["mode"],
        )
        for value in bounded:
            self.assertLessEqual(len(value), MAX_TEXT_CHARS)
        self.assertLessEqual(len(vehicle["vinSuffix"]), 6)
        # Non-string passthroughs were unbounded too: an arbitrary JSON value
        # here defeats a per-string cap on its own.
        self.assertIsNone(vehicle["modelYear"])
        self.assertIsNone(vehicle["online"])

    def test_normalize_vehicle_keeps_ordinary_values_intact(self):
        vehicle = normalize_vehicle(
            {"id": "vehicle-1", "vin": "7FCTGAAA1NN012345", "name": "Adventure", "vehicle": {"model": "R1T", "modelYear": 2024}},
            {"otaCurrentVersion": record("2026.14.02"), "cloudConnection": {"isOnline": True, "lastSync": "2026-08-25T12:02:00Z"}},
            False,
        )
        self.assertEqual(vehicle["name"], "Adventure")
        self.assertEqual(vehicle["modelYear"], 2024)
        self.assertIs(vehicle["online"], True)
        self.assertEqual(vehicle["softwareVersion"], "2026.14.02")

    def test_state_built_from_oversized_api_strings_can_be_read_back(self):
        """The helper must never write a state.json its own reader refuses."""
        huge = "A" * 5000
        vehicles = []
        for index in range(MAX_VEHICLES):
            vehicles.append(normalize_vehicle(
                {"id": f"{index}-{huge}", "vin": huge, "name": huge, "vehicle": {"model": huge, "modelYear": 2024}},
                {
                    "powerState": record(huge, huge),
                    "chargerState": record(huge, huge),
                    "cabinPreconditioningType": record(huge, huge),
                    "otaCurrentVersion": record(huge, huge),
                    "cloudConnection": {"isOnline": True, "lastSync": huge},
                    "gnssLocation": {"latitude": 1.0, "longitude": 2.0, "isAuthorized": True, "timeStamp": huge},
                },
                True,
            ))
        payload = {
            "schemaVersion": 1, "status": "linked", "message": "", "polledAt": "2026-08-25T12:00:00Z",
            "selectedVehicleId": vehicles[0]["id"], "locationEnabled": True, "vehicles": vehicles,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with mock.patch.object(store, "STATE_FILE", path):
                store.write_state(payload)
                recovered = store.read_state()
                written = path.stat().st_size
        self.assertLessEqual(written, store.MAX_LOCAL_JSON_BYTES)
        self.assertEqual(recovered["status"], "linked")
        self.assertEqual(len(recovered["vehicles"]), MAX_VEHICLES)

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
            [("vehicle-1", {
                "body.locks.states",
                "body.closures.states",
                "comfort.cabin.cabin_preconditioning_status",
                "comfort.cabin.cabin_temperatures",
                "comfort.cabin.hvac_settings_status",
                "vehicle.power.state",
            })],
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
                "cabinClimateInteriorTemperature": 20.0,
                "cabinClimateDriverTemperature": 21.0,
                "cabinPreconditioningStatus": "off",
                "cabinPreconditioningType": "none",
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
        complete_security["cabinClimateInteriorTemperature"] = record(20.0)
        complete_security["cabinClimateDriverTemperature"] = record(21.0)
        complete_security["cabinPreconditioningStatus"] = record("off")
        complete_security["cabinPreconditioningType"] = record("none")
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

    def test_driving_vehicle_does_not_show_stale_charging_state(self):
        vehicle = normalize_vehicle(
            {"id": "vehicle-1"},
            {
                "powerState": record("go", "2026-08-26T11:39:18Z"),
                "chargerState": record("charging_ready", "2026-08-25T17:58:11Z"),
                "timeToEndOfCharge": record(0, "2026-08-25T17:58:19Z"),
            },
            False,
        )

        self.assertEqual(vehicle["powerState"], "driving")
        self.assertEqual(vehicle["charging"]["state"], "not_charging")
        self.assertFalse(vehicle["charging"]["charging"])
        self.assertFalse(vehicle["charging"]["pluggedIn"])
        self.assertIsNone(vehicle["charging"]["minutesRemaining"])

    def test_charging_ready_is_not_reported_as_charging(self):
        # "charging_ready" means the vehicle is ready to charge and is not
        # connected. Substring matching used to read the "charging" prefix as
        # an active session and show a parked car as plugged in and charging.
        vehicle = normalize_vehicle(
            {"id": "vehicle-1"},
            {
                "powerState": record("sleeping", "2026-09-02T19:50:09Z"),
                "chargerState": record("charging_ready", "2026-09-01T19:54:28Z"),
                "timeToEndOfCharge": record(0, "2026-09-01T19:55:35Z"),
            },
            False,
        )

        self.assertEqual(vehicle["charging"]["state"], "charging_ready")
        self.assertFalse(vehicle["charging"]["charging"])
        self.assertFalse(vehicle["charging"]["pluggedIn"])
        self.assertIsNone(vehicle["charging"]["minutesRemaining"])

    def test_charger_states_map_to_charging_and_plug(self):
        expected = {
            "charging_active": (True, True),
            "charging_connecting": (False, True),
            "charging_complete": (False, True),
            "charging_schedule_request": (False, True),
            "charging_interrupted": (False, True),
            "charging_error": (False, None),
            "charging_ready": (False, False),
            "chrgr_sts_connected_charging": (True, True),
            "chrgr_sts_connected_no_chrg": (False, True),
            "chrgr_sts_not_connected": (False, False),
        }
        for state, (charging, plugged) in expected.items():
            with self.subTest(state=state):
                vehicle = normalize_vehicle({"id": "vehicle-1"}, {"chargerState": record(state)}, False)
                self.assertEqual(vehicle["charging"]["state"], state)
                self.assertEqual(vehicle["charging"]["charging"], charging)
                self.assertEqual(vehicle["charging"]["pluggedIn"], plugged)

    def test_unrecognized_charger_state_leaves_the_plug_undecided(self):
        # A future enum value must not be guessed into a plug that may not be
        # there; the reported token still reaches the panel.
        vehicle = normalize_vehicle({"id": "vehicle-1"}, {"chargerState": record("charging_moon_beam")}, False)

        self.assertEqual(vehicle["charging"]["state"], "charging_moon_beam")
        self.assertFalse(vehicle["charging"]["charging"])
        self.assertIsNone(vehicle["charging"]["pluggedIn"])

    def test_charger_status_answers_when_charger_state_is_absent(self):
        vehicle = normalize_vehicle(
            {"id": "vehicle-1"},
            {"chargerStatus": record("chrgr_sts_connected_no_chrg"), "timeToEndOfCharge": record(0)},
            False,
        )

        self.assertFalse(vehicle["charging"]["charging"])
        self.assertTrue(vehicle["charging"]["pluggedIn"])

    def test_normalize_vehicle_includes_r2_climate_target(self):
        vehicle = normalize_vehicle(
            {"id": "vehicle-1"},
            {
                "cabinClimateInteriorTemperature": record(24.6),
                "cabinClimateDriverTemperature": record(24.0),
                "cabinPreconditioningStatus": record("active"),
                "cabinPreconditioningType": record("heating"),
            },
            False,
        )

        self.assertEqual(vehicle["climate"]["cabinC"], 24.6)
        self.assertEqual(vehicle["climate"]["targetC"], 24.0)
        self.assertTrue(vehicle["climate"]["active"])
        self.assertEqual(vehicle["climate"]["mode"], "heating")

    def test_normalize_vehicle_keeps_unknown_climate_inactive(self):
        vehicle = normalize_vehicle(
            {"id": "vehicle-1"},
            {"cabinPreconditioningStatus": record("unknown")},
            False,
        )

        self.assertFalse(vehicle["climate"]["active"])

    def test_vehicle_list_rejects_malformed_shapes(self):
        client = RivianReadClient()
        for current_user in ("invalid", ["invalid"], {"vehicles": ["invalid"]}):
            with self.subTest(current_user=current_user):
                client._post = lambda *args, value=current_user, **kwargs: {
                    "currentUser": value
                }
                with self.assertRaisesRegex(ApiError, "vehicle list response changed"):
                    client.vehicles()

    def test_vehicle_list_rejects_unbounded_fanout(self):
        client = RivianReadClient()
        client._post = lambda *args, **kwargs: {
            "currentUser": {"vehicles": [{"id": str(index)} for index in range(33)]}
        }
        with self.assertRaisesRegex(ApiError, "too many vehicles"):
            client.vehicles()

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
