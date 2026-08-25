import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import omarivian.store as store


class StoreTests(unittest.TestCase):
    def test_state_file_is_private_and_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with mock.patch.object(store, "STATE_FILE", path):
                store.write_state({"status": "linked"})
                self.assertEqual(json.loads(path.read_text()), {"status": "linked"})
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_clear_local_data_removes_state_preferences_and_artwork(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            prefs_path = Path(directory) / "preferences.json"
            cache_path = Path(directory) / "vehicle-artwork"
            state_path.write_text("secret-derived state")
            prefs_path.write_text("preferences")
            cache_path.mkdir()
            (cache_path / "image.png").write_bytes(b"image")
            with mock.patch.object(store, "STATE_FILE", state_path), mock.patch.object(
                store, "PREFS_FILE", prefs_path
            ), mock.patch.object(store, "CACHE_DIR", cache_path):
                store.clear_local_data()
            self.assertFalse(state_path.exists())
            self.assertFalse(prefs_path.exists())
            self.assertFalse(cache_path.exists())

    def test_artwork_cache_is_private_and_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "vehicle-artwork"
            with mock.patch.object(store, "CACHE_DIR", cache_path):
                path = store.write_artwork("vehicle-1", "https://cdn.example/car.png", b"image", ".png")
                self.assertEqual(path.read_bytes(), b"image")
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
                self.assertEqual(store.cached_artwork("vehicle-1", "https://cdn.example/car.png"), path)

    def test_clear_tokens_uses_matching_secret_attributes(self):
        with mock.patch.object(store, "_secret_tool") as secret_tool:
            store.clear_tokens()
            secret_tool.assert_called_once_with(
                "clear", "application", "omarivian", "account", "default"
            )


if __name__ == "__main__":
    unittest.main()
