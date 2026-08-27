"""Secret Service credentials and private local state."""
from __future__ import annotations
import fcntl
import hashlib, json, os, selectors, shutil, stat, subprocess, tempfile, time
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
KEYRING_TIMEOUT_SECONDS = 30.0
COMMAND_LOCK_TIMEOUT_SECONDS = 30.0
MAX_ARTWORK_FILES_PER_VEHICLE = 32


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise OSError(f"Refusing unsafe private directory: {path}")
    os.chmod(path, 0o700, follow_symlinks=False)


def _open_regular(path: Path, flags: int, mode: int = 0o600) -> int:
    """Open one leaf without following links and require a regular file."""
    fd = os.open(path, flags | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, mode)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"Refusing non-regular file: {path}")
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def command_lock() -> Iterator[None]:
    """Serialize helper commands that mutate shared credentials or state."""
    _ensure_private_directory(STATE_DIR)
    fd = _open_regular(STATE_DIR / ".command.lock", os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    try:
        os.fchmod(fd, 0o600)
        deadline = time.monotonic() + COMMAND_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Another OmaRivian command did not finish") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _secret_tool(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["secret-tool", *args],
            input=input_text,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=KEYRING_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("secret-tool is required (package: libsecret)") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("System keyring request timed out") from exc


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
    body = bytearray()
    deadline = time.monotonic() + KEYRING_TIMEOUT_SECONDS
    selector = selectors.DefaultSelector()
    try:
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("System keyring request timed out")
            if not selector.select(remaining):
                raise RuntimeError("System keyring request timed out")
            chunk = os.read(process.stdout.fileno(), MAX_KEYRING_BYTES + 1 - len(body))
            if not chunk:
                # The write end is closed; select() would report readable forever.
                break
            body.extend(chunk)
            if len(body) > MAX_KEYRING_BYTES:
                raise RuntimeError("System keyring response was too large")
        while len(body) <= MAX_KEYRING_BYTES:
            chunk = os.read(process.stdout.fileno(), MAX_KEYRING_BYTES + 1 - len(body))
            if not chunk:
                break
            body.extend(chunk)
        if len(body) > MAX_KEYRING_BYTES:
            raise RuntimeError("System keyring response was too large")
        try:
            returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("System keyring request timed out") from exc
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait()
        raise
    finally:
        selector.close()
        process.stdout.close()
    try:
        return returncode, bytes(body).decode("utf-8")
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
    result = _secret_tool("clear", "application", SERVICE, "account", "default")
    if result.returncode != 0:
        raise RuntimeError("Could not clear the saved Rivian session")


def clear_local_data() -> list[Path]:
    """Remove local state, preferences and cached artwork best-effort.

    Returns the paths that survived so the caller can report identifying
    residue instead of aborting the rest of the unlink.
    """
    failures = []
    for path in (STATE_FILE, PREFS_FILE):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            failures.append(path)
    try:
        shutil.rmtree(CACHE_DIR)
    except FileNotFoundError:
        pass
    except OSError:
        failures.append(CACHE_DIR)
    try:
        if CACHE_DIR.exists() and CACHE_DIR not in failures:
            failures.append(CACHE_DIR)
    except OSError:
        if CACHE_DIR not in failures:
            failures.append(CACHE_DIR)
    return failures


def cached_artwork(vehicle_id: str, source_url: str) -> Path | None:
    directory = CACHE_DIR / hashlib.sha256(vehicle_id.encode()).hexdigest()[:16]
    source_key = hashlib.sha256(source_url.encode()).hexdigest()
    for extension in (".png", ".webp", ".jpg"):
        path = directory / f"{source_key}{extension}"
        try:
            if stat.S_ISREG(path.lstat().st_mode):
                return path
        except FileNotFoundError:
            continue
    return None


def write_artwork(vehicle_id: str, source_url: str, body: bytes, extension: str) -> Path:
    directory = CACHE_DIR / hashlib.sha256(vehicle_id.encode()).hexdigest()[:16]
    for private_directory in (CACHE_DIR.parent, CACHE_DIR, directory):
        _ensure_private_directory(private_directory)
    siblings = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if len(siblings) >= MAX_ARTWORK_FILES_PER_VEHICLE:
                raise OSError("Artwork cache contains too many files")
            siblings.append(Path(entry.path))
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
    for sibling in siblings:
        if sibling == path:
            continue
        try:
            sibling.unlink()
        except FileNotFoundError:
            continue
    return path


def _read_json(path: Path, default: dict) -> dict:
    try:
        fd = _open_regular(path, os.O_RDONLY)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return default
            with os.fdopen(fd, "rb") as handle:
                fd = -1
                raw = handle.read(MAX_LOCAL_JSON_BYTES + 1)
        finally:
            if fd >= 0:
                os.close(fd)
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
    payload = json.dumps(data, separators=(",", ":")) + "\n"
    # _read_json refuses anything past this cap, so writing past it would leave
    # a file the helper can never read back.
    if len(payload.encode()) > MAX_LOCAL_JSON_BYTES:
        raise RuntimeError(f"Refusing to write oversized {path.name}")
    _ensure_private_directory(path.parent)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(payload)
        os.chmod(temp_name, 0o600); os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
