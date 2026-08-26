import base64
import json
import struct
import unittest
from pathlib import Path
from typing import Any

from omarivian.parallax import ParallaxError, _WebSocket, decode_topic, snapshot


FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "parallax_r2_security.json").read_text())


class FakeStream:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)


class FakeWebSocket:
    def __init__(self, messages):
        self.stream = FakeStream()
        self.messages = list(messages)
        self.sent = []
        self.closed = False

    def send_json(self, value):
        self.sent.append(value)

    def receive_text(self):
        if not self.messages:
            raise AssertionError("No scripted WebSocket message remains")
        message = self.messages.pop(0)
        if message.get("id") == "$subscription":
            subscribe = next(item for item in self.sent if item["type"] == "subscribe")
            message["id"] = subscribe["id"]
        return json.dumps(message)

    def close(self):
        self.closed = True


class ByteStream:
    def __init__(self, incoming):
        self.incoming = bytearray(incoming)
        self.sent = bytearray()
        self.closed = False

    def recv(self, length):
        chunk = bytes(self.incoming[:length])
        del self.incoming[:length]
        return chunk

    def sendall(self, value):
        self.sent.extend(value)

    def close(self):
        self.closed = True


def server_frame(opcode, payload=b"", *, final=True, masked=False):
    first = (0x80 if final else 0) | opcode
    second = (0x80 if masked else 0) | len(payload)
    frame = bytes((first, second))
    if masked:
        frame += b"mask" + bytes(byte ^ b"mask"[index % 4] for index, byte in enumerate(payload))
    else:
        frame += payload
    return frame


class ParallaxTests(unittest.TestCase):
    def test_redacted_r2_fixture_decodes_locks_and_closures(self):
        locks = decode_topic(
            "body.locks.states",
            FIXTURE["payloads"]["body.locks.states"],
            1_777_333_600_000,
        )
        closures = decode_topic(
            "body.closures.states",
            FIXTURE["payloads"]["body.closures.states"],
            1_777_333_600_000,
        )

        self.assertEqual(set(locks), {
            "doorFrontLeftLocked", "doorFrontRightLocked",
            "doorRearLeftLocked", "doorRearRightLocked",
            "closureFrunkLocked", "closureLiftgateLocked",
        })
        self.assertTrue(all(item["value"] == "locked" for item in locks.values()))
        self.assertEqual(set(closures), {
            "doorFrontLeftClosed", "doorFrontRightClosed",
            "doorRearLeftClosed", "doorRearRightClosed",
            "closureFrunkClosed", "closureLiftgateClosed",
        })
        self.assertTrue(all(item["value"] == "closed" for item in closures.values()))

    def test_redacted_r2_fixture_decodes_sleeping_power_state(self):
        power = decode_topic(
            "vehicle.power.state",
            FIXTURE["payloads"]["vehicle.power.state"],
            1_777_333_600_000,
        )
        self.assertEqual(power["powerState"]["value"], "sleeping")

    def test_snapshot_subscribes_only_to_requested_non_location_topics(self):
        messages = [
            {"type": "connection_ack"},
            {
                "type": "next",
                "id": "$subscription",
                "payload": {"data": {"parallaxMessages": {
                    "rvm": "body.locks.states",
                    "payload": FIXTURE["payloads"]["body.locks.states"],
                    "timestamp": 1_777_333_600_000,
                }}},
            },
        ]
        websocket = FakeWebSocket(messages)
        dialer: Any = lambda _headers, _timeout: websocket

        result = snapshot(
            "vehicle-1",
            {"body.locks.states"},
            app_session_token="app",
            user_session_token="user",
            csrf_token="csrf",
            dialer=dialer,
        )

        subscribe = next(item for item in websocket.sent if item["type"] == "subscribe")
        serialized = json.dumps(subscribe).lower()
        self.assertNotIn("gnss", serialized)
        self.assertNotIn("latitude", serialized)
        self.assertNotIn("longitude", serialized)
        self.assertEqual(subscribe["payload"]["variables"]["rvms"], ["body.locks.states"])
        self.assertEqual(result["doorFrontLeftLocked"]["value"], "locked")
        self.assertTrue(websocket.closed)

    def test_gnss_is_decoded_only_when_explicitly_requested(self):
        payload = base64.b64encode(
            b"\x09" + struct.pack("<d", 35.0)
            + b"\x11" + struct.pack("<d", -80.0)
        ).decode()
        messages = [
            {"type": "connection_ack"},
            {
                "type": "next",
                "id": "$subscription",
                "payload": {"data": {"parallaxMessages": {
                    "rvm": "dynamics.vehicle.gnss",
                    "payload": payload,
                    "timestamp": 1_777_333_600_000,
                }}},
            },
        ]
        websocket = FakeWebSocket(messages)
        dialer: Any = lambda _headers, _timeout: websocket

        result = snapshot(
            "vehicle-1",
            {"dynamics.vehicle.gnss"},
            app_session_token="app",
            user_session_token="user",
            csrf_token="csrf",
            dialer=dialer,
        )

        self.assertEqual(result["gnssLocation"]["latitude"], 35.0)
        self.assertEqual(result["gnssLocation"]["longitude"], -80.0)

    def test_snapshot_rejects_malformed_graphql_shapes_as_fallback_errors(self):
        websocket = FakeWebSocket([
            {"type": "connection_ack"},
            {"type": "next", "id": "$subscription", "payload": []},
        ])
        dialer: Any = lambda _headers, _timeout: websocket

        with self.assertRaises(ParallaxError):
            snapshot(
                "vehicle-1",
                {"body.locks.states"},
                app_session_token="app",
                user_session_token="user",
                csrf_token="csrf",
                dialer=dialer,
            )
        self.assertTrue(websocket.closed)

    def test_snapshot_ignores_other_operation_ids_and_handles_pings(self):
        messages = [
            {"type": "ping"},
            {"type": "connection_ack"},
            {"type": "complete", "id": "another-operation"},
            {"type": "ping", "payload": {"nonce": 1}},
            {
                "type": "next",
                "id": "$subscription",
                "payload": {"data": {"parallaxMessages": {
                    "rvm": "body.locks.states",
                    "payload": FIXTURE["payloads"]["body.locks.states"],
                    "timestamp": 1_777_333_600_000,
                }}},
            },
        ]
        websocket = FakeWebSocket(messages)
        dialer: Any = lambda _headers, _timeout: websocket

        result = snapshot(
            "vehicle-1",
            {"body.locks.states"},
            app_session_token="app",
            user_session_token="user",
            csrf_token="csrf",
            dialer=dialer,
        )

        pongs = [item for item in websocket.sent if item["type"] == "pong"]
        self.assertEqual(pongs, [{"type": "pong"}, {"type": "pong", "payload": {"nonce": 1}}])
        self.assertEqual(result["doorFrontLeftLocked"]["value"], "locked")

    def test_protobuf_field_count_is_bounded(self):
        payload = base64.b64encode(b"\x08\x00" * 4097).decode()
        with self.assertRaises(ParallaxError):
            decode_topic("body.locks.states", payload, 1_777_333_600_000)

    def test_websocket_reassembles_fragmented_text_and_answers_ping(self):
        incoming = (
            server_frame(0x9, b"ok")
            + server_frame(0x1, b'{"type":', final=False)
            + server_frame(0x0, b'"next"}')
        )
        stream = ByteStream(incoming)
        stream_for_test: Any = stream
        websocket = _WebSocket(stream_for_test)

        self.assertEqual(websocket.receive_text(), '{"type":"next"}')
        self.assertEqual(stream.sent[0] & 0x0F, 0x0A)
        self.assertTrue(stream.sent[1] & 0x80)

    def test_websocket_rejects_masked_server_frames(self):
        stream_for_test: Any = ByteStream(server_frame(0x1, b"bad", masked=True))
        websocket = _WebSocket(stream_for_test)
        with self.assertRaises(ParallaxError):
            websocket.receive_text()


if __name__ == "__main__":
    unittest.main()
