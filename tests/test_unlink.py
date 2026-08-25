import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import omarivian.cli as cli
import omarivian.store as store


class UnlinkTests(unittest.TestCase):
    def test_unlink_clears_tokens_preferences_and_vehicle_data(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            prefs_path = Path(directory) / "preferences.json"
            cache_path = Path(directory) / "vehicle-artwork"
            with mock.patch.object(store, "STATE_FILE", state_path), mock.patch.object(
                store, "PREFS_FILE", prefs_path
            ), mock.patch.object(store, "CACHE_DIR", cache_path), mock.patch.object(cli, "clear_tokens"), mock.patch.object(
                cli, "clear_local_data", store.clear_local_data
            ), mock.patch.object(cli, "write_state", store.write_state):
                store.write_preferences({"locationEnabled": True})
                cli.command_unlink(argparse.Namespace())
                saved = store.read_state()
                self.assertEqual(saved["status"], "unlinked")
                self.assertFalse(saved["locationEnabled"])
                self.assertEqual(saved["vehicles"], [])
                self.assertFalse(prefs_path.exists())


if __name__ == "__main__":
    unittest.main()
