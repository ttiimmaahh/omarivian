import argparse
import contextlib
import io
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

    def test_unlink_records_unlinked_state_even_when_local_data_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            prefs_path = Path(directory) / "preferences.json"
            cache_path = Path(directory) / "vehicle-artwork"
            cache_path.mkdir()
            (cache_path / "render.png").write_bytes(b"identifying render")
            stderr = io.StringIO()
            with mock.patch.object(store, "STATE_FILE", state_path), mock.patch.object(
                store, "PREFS_FILE", prefs_path
            ), mock.patch.object(store, "CACHE_DIR", cache_path), mock.patch.object(
                cli, "clear_tokens"
            ), mock.patch.object(cli, "clear_local_data", store.clear_local_data), mock.patch.object(
                cli, "write_state", store.write_state
            ), mock.patch.object(
                store.shutil, "rmtree", lambda path, ignore_errors=False: None
            ), contextlib.redirect_stderr(stderr):
                result = cli.command_unlink(argparse.Namespace())
                saved = store.read_state()

        # The credentials really were cleared, so the panel must read "unlinked".
        self.assertEqual(saved["status"], "unlinked")
        self.assertEqual(saved["vehicles"], [])
        # Panel.qml onExited only surfaces stderr above exit code 3, so leftover
        # identifying files must not be reported below that threshold.
        self.assertGreater(result, 3)
        self.assertIn(str(cache_path), stderr.getvalue())

    def test_unlink_reports_state_path_when_unlinked_state_cannot_be_written(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.mkdir()
            stderr = io.StringIO()
            with mock.patch.object(store, "STATE_FILE", state_path), mock.patch.object(
                store, "PREFS_FILE", Path(directory) / "preferences.json"
            ), mock.patch.object(store, "CACHE_DIR", Path(directory) / "vehicle-artwork"), mock.patch.object(
                cli, "clear_tokens"
            ), mock.patch.object(cli, "clear_local_data", store.clear_local_data), mock.patch.object(
                cli, "write_state", store.write_state
            ), contextlib.redirect_stderr(stderr):
                result = cli.command_unlink(argparse.Namespace())

        self.assertEqual(result, 4)
        self.assertIn(str(state_path), stderr.getvalue())

    def test_unlink_succeeds_quietly_when_everything_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            stderr = io.StringIO()
            with mock.patch.object(store, "STATE_FILE", Path(directory) / "state.json"), mock.patch.object(
                store, "PREFS_FILE", Path(directory) / "preferences.json"
            ), mock.patch.object(store, "CACHE_DIR", Path(directory) / "vehicle-artwork"), mock.patch.object(
                cli, "clear_tokens"
            ), mock.patch.object(cli, "clear_local_data", store.clear_local_data), mock.patch.object(
                cli, "write_state", store.write_state
            ), contextlib.redirect_stderr(stderr):
                result = cli.command_unlink(argparse.Namespace())

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")

    def test_unlink_does_not_clear_local_state_when_token_deletion_fails(self):
        with mock.patch.object(
            cli, "clear_tokens", side_effect=RuntimeError("keyring unavailable")
        ), mock.patch.object(cli, "clear_local_data") as clear_local_data, mock.patch.object(
            cli, "write_state"
        ) as write_state, mock.patch("sys.stderr"):
            result = cli.command_unlink(argparse.Namespace())

        self.assertEqual(result, 1)
        clear_local_data.assert_not_called()
        write_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
