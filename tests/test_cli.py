import json
import math
import unittest

from omarivian.api import AuthenticationError, RivianReadClient, Tokens
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
