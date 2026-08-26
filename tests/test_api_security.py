import json
import threading
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
