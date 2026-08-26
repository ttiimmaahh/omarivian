import json
import os
import stat
import subprocess
import sys
import tempfile
import time
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

    def test_clear_local_data_reports_paths_it_could_not_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            prefs_path = Path(directory) / "preferences.json"
            cache_path = Path(directory) / "vehicle-artwork"
            # A directory in the state file's place makes unlink() raise
            # IsADirectoryError, an OSError that is not FileNotFoundError.
            state_path.mkdir()
            prefs_path.write_text("preferences")
            cache_path.mkdir()
            with mock.patch.object(store, "STATE_FILE", state_path), mock.patch.object(
                store, "PREFS_FILE", prefs_path
            ), mock.patch.object(store, "CACHE_DIR", cache_path):
                failures = store.clear_local_data()
            # Everything that could go, went; the rest is reported, not raised.
            self.assertFalse(prefs_path.exists())
            self.assertEqual(failures, [state_path])

    def test_clear_local_data_reports_artwork_cache_that_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "vehicle-artwork"
            cache_path.mkdir()
            (cache_path / "render.png").write_bytes(b"image")
            with mock.patch.object(store, "STATE_FILE", Path(directory) / "state.json"), mock.patch.object(
                store, "PREFS_FILE", Path(directory) / "preferences.json"
            ), mock.patch.object(store, "CACHE_DIR", cache_path), mock.patch.object(
                store.shutil, "rmtree", lambda path, ignore_errors=False: None
            ):
                failures = store.clear_local_data()
            self.assertEqual(failures, [cache_path])

    def test_oversized_state_is_refused_instead_of_written_unreadably(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with mock.patch.object(store, "STATE_FILE", path):
                with self.assertRaisesRegex(RuntimeError, "oversized"):
                    store.write_state({"blob": "x" * (store.MAX_LOCAL_JSON_BYTES + 1)})
                # No half-written file and no stray temp file left behind.
                self.assertFalse(path.exists())
                self.assertEqual(list(path.parent.iterdir()), [])

    def test_artwork_cache_is_private_and_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "vehicle-artwork"
            with mock.patch.object(store, "CACHE_DIR", cache_path):
                path = store.write_artwork("vehicle-1", "https://cdn.example/car.png", b"image", ".png")
                self.assertEqual(path.read_bytes(), b"image")
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
                self.assertEqual(store.cached_artwork("vehicle-1", "https://cdn.example/car.png"), path)

    def test_new_artwork_replaces_previous_source_url(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "vehicle-artwork"
            with mock.patch.object(store, "CACHE_DIR", cache_path):
                old_path = store.write_artwork(
                    "vehicle-1", "https://cdn.example/old.png", b"old", ".png"
                )
                new_path = store.write_artwork(
                    "vehicle-1", "https://cdn.example/new.webp", b"new", ".webp"
                )

            self.assertFalse(old_path.exists())
            self.assertEqual(new_path.read_bytes(), b"new")
            self.assertEqual(list(new_path.parent.iterdir()), [new_path])

    def test_cached_artwork_rejects_symlinked_file(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "vehicle-artwork"
            vehicle_directory = cache_path / store.hashlib.sha256(b"vehicle-1").hexdigest()[:16]
            vehicle_directory.mkdir(parents=True)
            victim = Path(directory) / "victim.png"
            victim.write_bytes(b"not-cache-owned")
            source_key = store.hashlib.sha256(b"https://cdn.example/car.png").hexdigest()
            (vehicle_directory / f"{source_key}.png").symlink_to(victim)
            with mock.patch.object(store, "CACHE_DIR", cache_path):
                self.assertIsNone(
                    store.cached_artwork("vehicle-1", "https://cdn.example/car.png")
                )

    def test_artwork_cache_rejects_symlinked_vehicle_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "vehicle-artwork"
            cache_path.mkdir()
            victim = Path(directory) / "victim"
            victim.mkdir()
            sentinel = victim / "keep.txt"
            sentinel.write_text("keep")
            vehicle_directory = cache_path / store.hashlib.sha256(b"vehicle-1").hexdigest()[:16]
            vehicle_directory.symlink_to(victim, target_is_directory=True)

            with mock.patch.object(store, "CACHE_DIR", cache_path):
                with self.assertRaisesRegex(OSError, "unsafe private directory"):
                    store.write_artwork(
                        "vehicle-1", "https://cdn.example/car.png", b"image", ".png"
                    )

            self.assertEqual(sentinel.read_text(), "keep")
            self.assertEqual(list(victim.iterdir()), [sentinel])

    def test_oversized_local_json_uses_safe_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            prefs_path = Path(directory) / "preferences.json"
            oversized = json.dumps({"value": "x" * (1024 * 1024)}).encode()
            state_path.write_bytes(oversized)
            prefs_path.write_bytes(oversized)
            with mock.patch.object(store, "STATE_FILE", state_path), mock.patch.object(
                store, "PREFS_FILE", prefs_path
            ):
                self.assertEqual(
                    store.read_state(),
                    {"schemaVersion": 1, "status": "unlinked", "vehicles": []},
                )
                self.assertEqual(
                    store.read_preferences(),
                    {"selectedVehicleId": "", "locationEnabled": False},
                )

    def test_local_json_fifo_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            os.mkfifo(path)
            script = (
                "from pathlib import Path; "
                "from omarivian.store import _read_json; "
                "assert _read_json(Path(__import__('sys').argv[1]), {'safe': True}) == {'safe': True}"
            )
            result = subprocess.run(
                [sys.executable, "-c", script, str(path)],
                cwd=Path(__file__).parents[1],
                timeout=2,
                check=False,
            )
            self.assertEqual(result.returncode, 0)

    def test_local_json_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            target.write_text('{"trusted":false}')
            path = Path(directory) / "state.json"
            path.symlink_to(target)
            self.assertEqual(store._read_json(path, {"trusted": True}), {"trusted": True})

    def test_command_lock_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            with mock.patch.object(store, "STATE_DIR", state_dir):
                with store.command_lock():
                    lock_path = state_dir / ".command.lock"
                    self.assertTrue(lock_path.exists())
                    self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)
                with store.command_lock():
                    pass

    def test_command_lock_rejects_symlinked_state_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            victim = Path(directory) / "victim"
            victim.mkdir()
            state_dir = Path(directory) / "state"
            state_dir.symlink_to(victim, target_is_directory=True)
            with mock.patch.object(store, "STATE_DIR", state_dir):
                with self.assertRaisesRegex(OSError, "unsafe private directory"):
                    with store.command_lock():
                        pass
            self.assertEqual(list(victim.iterdir()), [])

    def test_command_lock_rejects_fifo_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state_dir.mkdir()
            os.mkfifo(state_dir / ".command.lock")
            script = (
                "from pathlib import Path; from unittest import mock; "
                "import omarivian.store as store; "
                "patcher=mock.patch.object(store, 'STATE_DIR', Path(__import__('sys').argv[1])); "
                "patcher.start(); "
                "\ntry:\n with store.command_lock(): pass\nexcept OSError:\n pass\nelse:\n raise SystemExit(1)"
            )
            result = subprocess.run(
                [sys.executable, "-c", script, str(state_dir)],
                cwd=Path(__file__).parents[1],
                timeout=2,
                check=False,
            )
            self.assertEqual(result.returncode, 0)

    def test_oversized_keyring_stdout_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            secret_tool = Path(directory) / "secret-tool"
            secret_tool.write_text(
                f"#!{sys.executable}\n"
                "import sys\n"
                "sys.stdout.buffer.write(b'x' * 65537)\n"
            )
            secret_tool.chmod(0o700)
            path = directory + os.pathsep + os.environ.get("PATH", "")
            with mock.patch.dict(os.environ, {"PATH": path}):
                with self.assertRaisesRegex(RuntimeError, "too large"):
                    store.load_tokens()

    def test_keyring_lookup_times_out(self):
        with tempfile.TemporaryDirectory() as directory:
            secret_tool_path = Path(directory) / "secret-tool"
            secret_tool_path.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(10)\n")
            secret_tool_path.chmod(0o700)
            path = directory + os.pathsep + os.environ.get("PATH", "")
            with mock.patch.dict(os.environ, {"PATH": path}), mock.patch.object(
                store, "KEYRING_TIMEOUT_SECONDS", 0.05
            ):
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    store.load_tokens()

    def test_keyring_lookup_returns_the_stored_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            secret_tool = Path(directory) / "secret-tool"
            secret_tool.write_text(
                f"#!{sys.executable}\n"
                "import sys\n"
                "sys.stdout.write('stored-session')\n"
            )
            secret_tool.chmod(0o700)
            path = directory + os.pathsep + os.environ.get("PATH", "")
            with mock.patch.dict(os.environ, {"PATH": path}):
                self.assertEqual(store.load_tokens(), "stored-session")

    def test_keyring_reader_does_not_spin_when_stdout_closes_early(self):
        """A closed pipe stays select()-readable, so an ignored empty read burns a core."""
        with tempfile.TemporaryDirectory() as directory:
            secret_tool = Path(directory) / "secret-tool"
            secret_tool.write_text(
                f"#!{sys.executable}\n"
                "import os\n"
                "import sys\n"
                "import time as clock\n"
                "sys.stdout.write('stored-session')\n"
                "sys.stdout.flush()\n"
                "os.close(1)\n"
                "clock.sleep(30)\n"
            )
            secret_tool.chmod(0o700)
            path = directory + os.pathsep + os.environ.get("PATH", "")
            with mock.patch.dict(os.environ, {"PATH": path}), mock.patch.object(
                store, "KEYRING_TIMEOUT_SECONDS", 1.0
            ):
                started_cpu = time.process_time()
                started = time.monotonic()
                # The child never exits, so the bounded wait is what ends this.
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    store.load_tokens()
                spent_cpu = time.process_time() - started_cpu
                elapsed = time.monotonic() - started
        self.assertLess(spent_cpu, 0.3, "the drain loop spun instead of blocking")
        self.assertLess(elapsed, 10, "process.wait() was not bounded by the deadline")

    def test_clear_tokens_uses_matching_secret_attributes(self):
        with mock.patch.object(store, "_secret_tool") as secret_tool:
            secret_tool.return_value.returncode = 0
            store.clear_tokens()
            secret_tool.assert_called_once_with(
                "clear", "application", "omarivian", "account", "default"
            )

    def test_clear_tokens_rejects_failed_deletion(self):
        with mock.patch.object(store, "_secret_tool") as secret_tool:
            secret_tool.return_value.returncode = 1
            with self.assertRaisesRegex(RuntimeError, "Could not clear"):
                store.clear_tokens()


if __name__ == "__main__":
    unittest.main()
