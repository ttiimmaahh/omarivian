"""Secret Service credentials and private local state."""
from __future__ import annotations
import fcntl
import hashlib, json, os, shutil, subprocess, tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SERVICE = "omarivian"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / SERVICE
STATE_FILE = STATE_DIR / "state.json"
PREFS_FILE = STATE_DIR / "preferences.json"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / SERVICE / "vehicle-artwork"
MAX_LOCAL_JSON_BYTES = 1024 * 1024
MAX_KEYRING_BYTES = 64 * 1024


@contextmanager
def command_lock() -> Iterator[None]:
    """Serialize helper commands that mutate shared credentials or state."""
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = STATE_DIR / ".command.lock"
    with lock_path.open("a", encoding="utf-8") as lock_file:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _secret_tool(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["secret-tool", *args],
            input=input_text,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("secret-tool is required (package: libsecret)") from exc


def _read_secret_tool(*args: str) -> tuple[int, str]:
    try:
        process = subprocess.Popen(
            ["secret-tool", *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("secret-tool is required (package: libsecret)") from exc
    if process.stdout is None:
        process.kill()
        process.wait()
        raise RuntimeError("Could not read the system keyring")
    try:
        body = process.stdout.read(MAX_KEYRING_BYTES + 1)
        if len(body) > MAX_KEYRING_BYTES:
            process.kill()
            process.wait()
            raise RuntimeError("System keyring response was too large")
        returncode = process.wait()
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    finally:
        process.stdout.close()
    try:
        return returncode, body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("System keyring response was invalid") from exc

def save_tokens(raw: str) -> None:
    result = _secret_tool("store", "--label=OmaRivian Rivian session", "application", SERVICE, "account", "default", input_text=raw)
    if result.returncode != 0: raise RuntimeError("Could not unlock or write the system keyring")

def load_tokens() -> str | None:
    returncode, stdout = _read_secret_tool("lookup", "application", SERVICE, "account", "default")
    value = stdout.strip()
    return value if returncode == 0 and value else None

def clear_tokens() -> None:
    _secret_tool("clear", "application", SERVICE, "account", "default")


def clear_local_data() -> None:
    for path in (STATE_FILE, PREFS_FILE):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
    try:
        shutil.rmtree(CACHE_DIR)
    except FileNotFoundError:
        return


def cached_artwork(vehicle_id: str, source_url: str) -> Path | None:
    directory = CACHE_DIR / hashlib.sha256(vehicle_id.encode()).hexdigest()[:16]
    source_key = hashlib.sha256(source_url.encode()).hexdigest()
    for extension in (".png", ".webp", ".jpg"):
        path = directory / f"{source_key}{extension}"
        if path.is_file():
            return path
    return None


def write_artwork(vehicle_id: str, source_url: str, body: bytes, extension: str) -> Path:
    directory = CACHE_DIR / hashlib.sha256(vehicle_id.encode()).hexdigest()[:16]
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(CACHE_DIR.parent, 0o700)
    os.chmod(CACHE_DIR, 0o700)
    os.chmod(directory, 0o700)
    source_key = hashlib.sha256(source_url.encode()).hexdigest()
    path = directory / f"{source_key}{extension}"
    fd, temp_name = tempfile.mkstemp(prefix=".artwork.", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    for sibling in directory.iterdir():
        if sibling != path:
            sibling.unlink(missing_ok=True)
    return path


def _read_json(path: Path, default: dict) -> dict:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_LOCAL_JSON_BYTES + 1)
        if len(raw) > MAX_LOCAL_JSON_BYTES:
            return default
        value = json.loads(raw)
        return value if isinstance(value, dict) else default
    except (OSError, ValueError):
        return default


def read_preferences() -> dict:
    return _read_json(PREFS_FILE, {"selectedVehicleId": "", "locationEnabled": False})

def write_preferences(data: dict) -> None:
    _atomic_json(PREFS_FILE, data)

def write_state(data: dict) -> None:
    _atomic_json(STATE_FILE, data)

def read_state() -> dict:
    return _read_json(STATE_FILE, {"schemaVersion": 1, "status": "unlinked", "vehicles": []})

def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, separators=(",", ":")); handle.write("\n")
        os.chmod(temp_name, 0o600); os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
