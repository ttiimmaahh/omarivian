import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import omarivian.api as api


MAX_GRAPHQL_RESPONSE_BYTES = 2 * 1024 * 1024


class _Server:
    def __init__(self, handler):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self):
        address = self.httpd.server_address
        return f"http://{address[0]}:{address[1]}/graphql"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.httpd.shutdown()
        self.thread.join()
        self.httpd.server_close()


class ApiTransportSecurityTests(unittest.TestCase):
    def test_graphql_response_over_byte_limit_is_rejected(self):
        body = json.dumps({"data": {"blob": "x" * MAX_GRAPHQL_RESPONSE_BYTES}}).encode()

        class OversizedResponse(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    return

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        with _Server(OversizedResponse) as server, mock.patch.object(api, "GATEWAY", server.url):
            with self.assertRaisesRegex(api.ApiError, "too large"):
                api.RivianReadClient()._post("Test", "query Test { test }")

    def test_graphql_redirect_does_not_forward_session_headers(self):
        received_headers = {}

        class RedirectTarget(BaseHTTPRequestHandler):
            def do_GET(self):
                received_headers.update(self.headers)
                body = b'{"data":{}}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        with _Server(RedirectTarget) as target:
            class RedirectOrigin(BaseHTTPRequestHandler):
                def do_POST(self):
                    self.send_response(302)
                    self.send_header("Location", target.url)
                    self.end_headers()

                def log_message(self, format: str, *args: object) -> None:
                    del format, args

            with _Server(RedirectOrigin) as origin, mock.patch.object(api, "GATEWAY", origin.url):
                tokens = api.Tokens(
                    access_token="access-secret",
                    user_session_token="session-secret",
                    app_session_token="app-secret",
                    csrf_token="csrf-secret",
                )
                with self.assertRaisesRegex(api.ApiError, "HTTP 302"):
                    api.RivianReadClient(tokens)._post(
                        "Test", "query Test { test }", authenticated=True
                    )

        self.assertNotIn("Authorization", received_headers)
        self.assertNotIn("U-Sess", received_headers)
        self.assertNotIn("A-Sess", received_headers)
        self.assertNotIn("Csrf-Token", received_headers)

    def test_malformed_graphql_errors_are_sanitized(self):
        client = api.RivianReadClient()
        malformed = (
            {"errors": "not-a-list"},
            {"errors": {}},
            {"errors": ["not-an-object"]},
            {"errors": [{"extensions": "not-an-object"}]},
            {"errors": [{"extensions": []}]},
            {"errors": [{"extensions": 0}]},
        )
        for body in malformed:
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.geturl.return_value = api.GATEWAY
            response.headers = {}
            response.read1.side_effect = [json.dumps(body).encode(), b""]
            with self.subTest(body=body), mock.patch.object(
                api._NO_REDIRECT_OPENER, "open", return_value=response
            ):
                with self.assertRaisesRegex(api.SchemaError, "malformed errors"):
                    client._post("Test", "query Test { test }")

    def test_capped_read_gives_up_on_a_trickling_response(self):
        """A read-exactly-n loop never returns to the deadline check."""

        class Trickling:
            headers: dict[str, str] = {}

            def __init__(self):
                self.read1_calls = 0

            def read(self, size):
                del size
                raise AssertionError("_read_capped must not use read(); it blocks for the full size")

            def read1(self, size):
                del size
                self.read1_calls += 1
                time.sleep(0.05)
                return b"x"

        response = Trickling()
        started = time.monotonic()
        with self.assertRaisesRegex(api.ApiError, "timed out"):
            api._read_capped(response, MAX_GRAPHQL_RESPONSE_BYTES, "Rivian response", timeout=0.3)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 5)
        self.assertGreater(response.read1_calls, 1)

    def test_graphql_read_deadline_survives_a_drip_feeding_server(self):
        body = json.dumps({"data": {"blob": "x" * 4096}}).encode()

        class DripResponse(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    for index in range(0, len(body), 2):
                        self.wfile.write(body[index:index + 2])
                        self.wfile.flush()
                        time.sleep(0.2)
                except OSError:
                    return

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        with _Server(DripResponse) as server, mock.patch.object(api, "GATEWAY", server.url):
            started = time.monotonic()
            # Either sanitized message is correct here; the security property is
            # that the call is bounded at all rather than holding the command lock.
            with self.assertRaises(api.ApiError):
                api.RivianReadClient(timeout=1)._post("Test", "query Test { test }")
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 10)

    def test_chunked_response_is_decoded_by_the_capped_read(self):
        """read1() must still decode chunked transfer-encoding, not hand back frames."""
        payload = {"data": {"currentUser": {"vehicles": [{"id": "vehicle-1"}]}}}
        body = json.dumps(payload).encode()

        class ChunkedResponse(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for index in range(0, len(body), 7):
                    piece = body[index:index + 7]
                    self.wfile.write(b"%X\r\n%s\r\n" % (len(piece), piece))
                self.wfile.write(b"0\r\n\r\n")

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        with _Server(ChunkedResponse) as server, mock.patch.object(api, "GATEWAY", server.url):
            data = api.RivianReadClient()._post("Test", "query Test { test }")
        self.assertEqual(data, payload["data"])

    def test_module_does_not_expose_redirect_following_urlopen(self):
        # urlopen uses the default opener and follows redirects; both call sites
        # must go through _NO_REDIRECT_OPENER instead.
        self.assertFalse(hasattr(api, "urlopen"))

    def test_artwork_redirect_is_rejected(self):
        target_requested = False

        class RedirectTarget(BaseHTTPRequestHandler):
            def do_GET(self):
                nonlocal target_requested
                target_requested = True
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(b"image")

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        with _Server(RedirectTarget) as target:
            class RedirectOrigin(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(302)
                    self.send_header("Location", target.url)
                    self.end_headers()

                def log_message(self, format: str, *args: object) -> None:
                    del format, args

            with _Server(RedirectOrigin) as origin, mock.patch.object(
                api, "_is_rivian_https_url", return_value=True
            ):
                with self.assertRaisesRegex(api.ApiError, "HTTP 302"):
                    api.RivianReadClient().download_artwork(origin.url)

        self.assertFalse(target_requested)


if __name__ == "__main__":
    unittest.main()
