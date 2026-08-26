"""Private, read-only Parallax snapshot client for newer Rivian vehicles.

The public CLI deliberately exposes no generic WebSocket or GraphQL surface. This
module connects to one fixed Rivian endpoint, subscribes to an allowlisted topic
set, and adapts known protobuf payloads to the legacy vehicle-state record shape.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

HOST = "api.rivian.com"
PATH = "/gql-consumer-subscriptions/graphql"
SUBPROTOCOL = "graphql-transport-ws"
CLIENT_NAME = "com.rivian.ios.consumer-apollo-ios"
CLIENT_VERSION = "1.13.0-1494"
MAX_HANDSHAKE_BYTES = 64 * 1024
MAX_MESSAGE_BYTES = 2 * 1024 * 1024
MAX_PROTOBUF_FIELDS = 4096
ALLOWED_TOPICS = frozenset({
    "body.closures.states",
    "body.locks.states",
    "comfort.cabin.cabin_preconditioning_status",
    "comfort.cabin.cabin_temperatures",
    "comfort.cabin.hvac_settings_status",
    "dynamics.vehicle.gnss",
    "vehicle.power.state",
})
SUBSCRIPTION = (
    "subscription ParallaxMessages($vehicleId: String!, $rvms: [String!]) { "
    "parallaxMessages(vehicleId: $vehicleId, rvms: $rvms) { payload timestamp rvm } }"
)

LOCK_MAP = {
    1: "doorFrontLeftLocked",
    2: "doorFrontRightLocked",
    3: "doorRearLeftLocked",
    4: "doorRearRightLocked",
    5: "closureFrunkLocked",
    7: "closureLiftgateLocked",
}
CLOSURE_MAP = {
    1: "doorFrontLeftClosed",
    2: "doorFrontRightClosed",
    3: "doorRearLeftClosed",
    4: "doorRearRightClosed",
    5: "closureFrunkClosed",
    7: "closureLiftgateClosed",
}


class ParallaxError(RuntimeError):
    """A sanitized Parallax transport or protocol failure."""


class ParallaxAuthenticationError(ParallaxError):
    """A sanitized Parallax session/authentication failure."""


def _header_value(value: str) -> str:
    if "\r" in value or "\n" in value or not value.isascii():
        raise ParallaxError("Invalid Rivian session metadata")
    return value


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift <= 63:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ParallaxError("Invalid Rivian Parallax payload")


def _protobuf_fields(data: bytes) -> Iterator[tuple[int, int, Any]]:
    offset = 0
    field_count = 0
    while offset < len(data):
        field_count += 1
        if field_count > MAX_PROTOBUF_FIELDS:
            raise ParallaxError("Rivian Parallax payload has too many fields")
        tag, offset = _read_varint(data, offset)
        number, wire_type = tag >> 3, tag & 0x07
        if number == 0:
            raise ParallaxError("Invalid Rivian Parallax payload")
        if wire_type == 0:
            value, offset = _read_varint(data, offset)
        elif wire_type == 1:
            if offset + 8 > len(data):
                raise ParallaxError("Invalid Rivian Parallax payload")
            value = data[offset : offset + 8]
            offset += 8
        elif wire_type == 2:
            length, offset = _read_varint(data, offset)
            if length > MAX_MESSAGE_BYTES or offset + length > len(data):
                raise ParallaxError("Invalid Rivian Parallax payload")
            value = data[offset : offset + length]
            offset += length
        elif wire_type == 5:
            if offset + 4 > len(data):
                raise ParallaxError("Invalid Rivian Parallax payload")
            value = data[offset : offset + 4]
            offset += 4
        else:
            raise ParallaxError("Unsupported Rivian Parallax payload")
        yield number, wire_type, value


def _timestamp(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError):
        return ""


def _record(value: Any, timestamp: Any) -> dict[str, Any]:
    return {"value": value, "timeStamp": _timestamp(timestamp)}


def _decode_float_field(payload: str, field_number: int, timestamp: Any) -> dict[str, Any] | None:
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, TypeError) as exc:
        raise ParallaxError("Invalid Rivian Parallax payload") from exc
    for number, wire_type, value in _protobuf_fields(raw):
        if number == field_number and wire_type == 5:
            decoded = struct.unpack("<f", value)[0]
            if -100.0 <= decoded <= 100.0:
                return _record(decoded, timestamp)
    return None


def _decode_states(payload: str, names: dict[int, str], values: dict[int, str], timestamp: Any) -> dict[str, Any]:
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, TypeError) as exc:
        raise ParallaxError("Invalid Rivian Parallax payload") from exc
    result: dict[str, Any] = {}
    for number, wire_type, nested in _protobuf_fields(raw):
        if number != 1 or wire_type != 2:
            continue
        state_id = None
        state_value = None
        for inner_number, inner_type, inner_value in _protobuf_fields(nested):
            if inner_type != 0:
                continue
            if inner_number == 1:
                state_id = inner_value
            elif inner_number == 2:
                state_value = inner_value
        name = names.get(state_id) if isinstance(state_id, int) else None
        text = values.get(state_value) if isinstance(state_value, int) else None
        if name and text:
            result[name] = _record(text, timestamp)
    return result


def decode_topic(topic: str, payload: str, timestamp: Any) -> dict[str, Any]:
    """Adapt one allowlisted Parallax payload to legacy vehicle-state fields."""
    if topic == "body.locks.states":
        return _decode_states(payload, LOCK_MAP, {1: "locked", 2: "unlocked"}, timestamp)
    if topic == "body.closures.states":
        return _decode_states(payload, CLOSURE_MAP, {1: "open", 2: "closed"}, timestamp)
    if topic == "comfort.cabin.cabin_temperatures":
        # Observed R2 field 3 correlates with cabinClimateInteriorTemperature.
        record = _decode_float_field(payload, 3, timestamp)
        return {"cabinClimateInteriorTemperature": record} if record else {}
    if topic == "comfort.cabin.hvac_settings_status":
        # Observed R2 field 1 is the driver's HVAC target in Celsius.
        record = _decode_float_field(payload, 1, timestamp)
        return {"cabinClimateDriverTemperature": record} if record else {}
    if topic == "comfort.cabin.cabin_preconditioning_status":
        try:
            raw = base64.b64decode(payload, validate=True)
        except (ValueError, TypeError) as exc:
            raise ParallaxError("Invalid Rivian Parallax payload") from exc
        for number, wire_type, value in _protobuf_fields(raw):
            # Enum 8 was correlated against the live Rivian app's Heating state.
            if number == 1 and wire_type == 0 and value == 8:
                return {
                    "cabinPreconditioningStatus": _record("active", timestamp),
                    "cabinPreconditioningType": _record("heating", timestamp),
                }
        return {}
    if topic == "vehicle.power.state":
        try:
            raw = base64.b64decode(payload, validate=True)
        except (ValueError, TypeError) as exc:
            raise ParallaxError("Invalid Rivian Parallax payload") from exc
        for number, wire_type, value in _protobuf_fields(raw):
            if number == 1 and wire_type == 0:
                power = {1: "sleeping", 2: "standby", 3: "ready", 4: "go"}.get(value)
                return {"powerState": _record(power, timestamp)} if power else {}
        return {}
    if topic == "dynamics.vehicle.gnss":
        try:
            raw = base64.b64decode(payload, validate=True)
        except (ValueError, TypeError) as exc:
            raise ParallaxError("Invalid Rivian Parallax payload") from exc
        latitude = None
        longitude = None
        for number, wire_type, value in _protobuf_fields(raw):
            if number == 1 and wire_type == 1:
                latitude = struct.unpack("<d", value)[0]
            elif number == 2 and wire_type == 1:
                longitude = struct.unpack("<d", value)[0]
        if latitude is None or longitude is None:
            return {}
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return {}
        return {
            "gnssLocation": {
                "latitude": latitude,
                "longitude": longitude,
                "timeStamp": _timestamp(timestamp),
                "isAuthorized": True,
            }
        }
    return {}


class _WebSocket:
    def __init__(self, stream: socket.socket, buffered: bytes = b""):
        self.stream = stream
        self.buffer = bytearray(buffered)
        self.deadline: float | None = None

    def set_deadline(self, deadline: float | None) -> None:
        self.deadline = deadline

    def close(self) -> None:
        try:
            self.send_frame(0x8, b"\x03\xe8")
        except (OSError, ParallaxError):
            # Best-effort close: the transport is closed below either way.
            self.stream.close()
            return
        self.stream.close()

    def _read_exact(self, length: int) -> bytes:
        while len(self.buffer) < length:
            if self.deadline is not None:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise ParallaxError("Rivian Parallax snapshot timed out")
                self.stream.settimeout(remaining)
            chunk = self.stream.recv(min(65536, length - len(self.buffer)))
            if not chunk:
                raise ParallaxError("Rivian closed the Parallax connection")
            self.buffer.extend(chunk)
        result = bytes(self.buffer[:length])
        del self.buffer[:length]
        return result

    def send_frame(self, opcode: int, payload: bytes) -> None:
        if len(payload) > MAX_MESSAGE_BYTES:
            raise ParallaxError("Rivian Parallax message is too large")
        first = 0x80 | opcode
        length = len(payload)
        if length < 126:
            header = bytes((first, 0x80 | length))
        elif length <= 0xFFFF:
            header = bytes((first, 0x80 | 126)) + struct.pack("!H", length)
        else:
            header = bytes((first, 0x80 | 127)) + struct.pack("!Q", length)
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.stream.sendall(header + mask + masked)

    def send_json(self, value: dict[str, Any]) -> None:
        self.send_frame(0x1, json.dumps(value, separators=(",", ":")).encode())

    def _frame(self) -> tuple[bool, int, bytes]:
        first, second = self._read_exact(2)
        fin = bool(first & 0x80)
        if first & 0x70:
            raise ParallaxError("Unsupported Rivian WebSocket extension")
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        if masked:
            raise ParallaxError("Invalid masked Rivian WebSocket frame")
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        if length > MAX_MESSAGE_BYTES:
            raise ParallaxError("Rivian Parallax message is too large")
        if opcode >= 0x8 and (not fin or length > 125):
            raise ParallaxError("Invalid Rivian WebSocket control frame")
        return fin, opcode, self._read_exact(length)

    def receive_text(self) -> str:
        parts: list[bytes] = []
        active = False
        total = 0
        while True:
            fin, opcode, payload = self._frame()
            if opcode == 0x8:
                raise ParallaxError("Rivian closed the Parallax connection")
            if opcode == 0x9:
                self.send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1 and not active:
                active = True
            elif opcode != 0x0 or not active:
                raise ParallaxError("Invalid Rivian WebSocket message")
            parts.append(payload)
            total += len(payload)
            if total > MAX_MESSAGE_BYTES:
                raise ParallaxError("Rivian Parallax message is too large")
            if fin:
                try:
                    return b"".join(parts).decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ParallaxError("Invalid Rivian WebSocket text") from exc


def _open_socket(headers: dict[str, str], timeout: float) -> _WebSocket:
    deadline = time.monotonic() + max(0.001, timeout)

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise ParallaxError("Rivian Parallax handshake timed out")
        return value

    key = base64.b64encode(os.urandom(16)).decode()
    lines = [
        f"GET {PATH} HTTP/1.1",
        f"Host: {HOST}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
        f"Sec-WebSocket-Protocol: {SUBPROTOCOL}",
    ]
    lines.extend(f"{name}: {_header_value(value)}" for name, value in headers.items() if value)
    request = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
    raw = socket.create_connection((HOST, 443), timeout=remaining())
    try:
        raw.settimeout(remaining())
        stream = ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)
        stream.settimeout(remaining())
        stream.sendall(request)
        response = bytearray()
        while b"\r\n\r\n" not in response:
            stream.settimeout(remaining())
            chunk = stream.recv(4096)
            if not chunk:
                raise ParallaxError("Rivian rejected the Parallax connection")
            response.extend(chunk)
            if len(response) > MAX_HANDSHAKE_BYTES:
                raise ParallaxError("Rivian Parallax handshake is too large")
        head, buffered = bytes(response).split(b"\r\n\r\n", 1)
        try:
            rows = head.decode("iso-8859-1").split("\r\n")
            status = rows[0].split()
            response_headers = {
                name.strip().lower(): value.strip()
                for row in rows[1:]
                for name, separator, value in [row.partition(":")]
                if separator
            }
        except (UnicodeDecodeError, ValueError) as exc:
            raise ParallaxError("Invalid Rivian Parallax handshake") from exc
        # RFC 6455 mandates SHA-1 here as a handshake checksum, not a security primitive.
        accept_source = (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
        accept_digest = hashlib.new("sha1", accept_source, usedforsecurity=False).digest()
        expected = base64.b64encode(accept_digest).decode()
        if len(status) < 2:
            raise ParallaxError("Rivian rejected the Parallax connection")
        if status[1] in {"401", "403"}:
            raise ParallaxAuthenticationError("Rivian Parallax session expired")
        if status[1] != "101":
            raise ParallaxError("Rivian rejected the Parallax connection")
        if response_headers.get("upgrade", "").lower() != "websocket":
            raise ParallaxError("Invalid Rivian Parallax handshake")
        if "upgrade" not in {part.strip().lower() for part in response_headers.get("connection", "").split(",")}:
            raise ParallaxError("Invalid Rivian Parallax handshake")
        if response_headers.get("sec-websocket-accept") != expected:
            raise ParallaxError("Invalid Rivian Parallax handshake")
        if response_headers.get("sec-websocket-protocol") != SUBPROTOCOL:
            raise ParallaxError("Invalid Rivian Parallax subprotocol")
        return _WebSocket(stream, buffered)
    except Exception:
        raw.close()
        raise


def _message(websocket: _WebSocket) -> dict[str, Any]:
    try:
        message = json.loads(websocket.receive_text())
    except (ValueError, TypeError) as exc:
        raise ParallaxError("Invalid Rivian Parallax message") from exc
    if not isinstance(message, dict):
        raise ParallaxError("Invalid Rivian Parallax message")
    return message


def _is_authentication_error(message: dict[str, Any]) -> bool:
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return False
    extensions = payload.get("extensions")
    code = extensions.get("code") if isinstance(extensions, dict) else payload.get("code")
    return str(code).upper() in {"401", "403", "UNAUTHENTICATED", "UNAUTHORIZED"}


def snapshot(
    vehicle_id: str,
    topics: set[str] | list[str] | tuple[str, ...],
    *,
    app_session_token: str,
    user_session_token: str,
    csrf_token: str,
    timeout: float = 8,
    dialer: Callable[[dict[str, str], float], _WebSocket] = _open_socket,
) -> dict[str, Any]:
    """Read one bounded snapshot for allowlisted topics and return legacy-shaped fields."""
    wanted = set(topics)
    if not wanted or not wanted.issubset(ALLOWED_TOPICS):
        return {}
    deadline = time.monotonic() + max(1.0, timeout)
    headers = {
        "A-Sess": app_session_token,
        "U-Sess": user_session_token,
        "Csrf-Token": csrf_token,
        "Apollographql-Client-Name": CLIENT_NAME,
    }
    websocket = dialer(headers, max(1.0, deadline - time.monotonic()))
    result: dict[str, Any] = {}
    subscription_id = str(uuid.uuid4())

    def answer_ping(message: dict[str, Any]) -> None:
        pong: dict[str, Any] = {"type": "pong"}
        if "payload" in message:
            pong["payload"] = message["payload"]
        websocket.send_json(pong)

    try:
        websocket.send_json({
            "type": "connection_init",
            "payload": {
                "client-name": CLIENT_NAME,
                "client-version": CLIENT_VERSION,
                "dc-cid": f"m-ios-{uuid.uuid4()}",
                "u-sess": user_session_token,
            },
        })
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ParallaxError("Rivian Parallax snapshot timed out")
            websocket.set_deadline(deadline)
            websocket.stream.settimeout(remaining)
            message = _message(websocket)
            kind = message.get("type")
            if kind == "ping":
                answer_ping(message)
                continue
            if kind == "connection_ack":
                break
            if kind in {"connection_error", "error"}:
                if _is_authentication_error(message):
                    raise ParallaxAuthenticationError("Rivian Parallax session expired")
                raise ParallaxError("Rivian rejected the Parallax session")
            if kind == "complete":
                raise ParallaxError("Rivian rejected the Parallax session")
        websocket.send_json({
            "type": "subscribe",
            "id": subscription_id,
            "payload": {
                "operationName": "ParallaxMessages",
                "variables": {"vehicleId": vehicle_id, "rvms": sorted(wanted)},
                "query": SUBSCRIPTION,
            },
        })
        while wanted:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            websocket.set_deadline(deadline)
            websocket.stream.settimeout(remaining)
            message = _message(websocket)
            kind = message.get("type")
            if kind == "ping":
                answer_ping(message)
                continue
            if kind not in {"next", "error", "complete"}:
                continue
            if message.get("id") != subscription_id:
                continue
            if kind == "error":
                raise ParallaxError("Rivian rejected the Parallax subscription")
            if kind == "complete":
                break
            envelope = message.get("payload")
            if not isinstance(envelope, dict):
                raise ParallaxError("Invalid Rivian Parallax message")
            data = envelope.get("data")
            if not isinstance(data, dict):
                raise ParallaxError("Invalid Rivian Parallax message")
            item = data.get("parallaxMessages")
            if not isinstance(item, dict):
                raise ParallaxError("Invalid Rivian Parallax message")
            topic = item.get("rvm")
            if topic not in wanted:
                continue
            payload = item.get("payload")
            if not isinstance(payload, str):
                raise ParallaxError("Invalid Rivian Parallax payload")
            result.update(decode_topic(topic, payload, item.get("timestamp")))
            wanted.remove(topic)
        websocket.send_json({"type": "complete", "id": subscription_id})
        return result
    except (OSError, TimeoutError, ssl.SSLError) as exc:
        raise ParallaxError("Could not read Rivian Parallax telemetry") from exc
    finally:
        websocket.close()
