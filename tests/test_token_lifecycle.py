"""Regression coverage for long-running polling without a background auth daemon."""
import argparse
import base64
import copy
import json
import unittest
from unittest import mock

from omarivian import cli
from omarivian.api import ApiError, AuthenticationError, RivianReadClient, Tokens


def jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


class TokenExpiryTests(unittest.TestCase):
    def test_expiry_and_five_minute_skew(self):
        tokens = Tokens(access_token=jwt({"exp": 2000}))
        self.assertFalse(tokens.access_expires_soon(now=1699))
        self.assertTrue(tokens.access_expires_soon(now=1700))
        self.assertTrue(tokens.access_expires_soon(now=2100))
        self.assertFalse(tokens.access_expires_soon(now=1700, leeway=0))

    def test_unknown_or_malformed_tokens_keep_reactive_retry(self):
        payloads = [{}, [], None, {"exp": True}, {"exp": "2000"}, {"exp": None},
                    {"exp": float("nan")}, {"exp": float("inf")}, {"exp": 10 ** 400}]
        values = ["", "opaque", "a.!.b", "a._w.b", "a.e30.b.extra", "x" * 17000]
        values.extend(jwt(payload) for payload in payloads)
        for value in values:
            with self.subTest(value=value[:40]):
                self.assertFalse(Tokens(access_token=value).access_expires_soon(now=1000))

    def test_old_keyring_format_roundtrips_without_expiry_metadata(self):
        tokens = Tokens.from_json(json.dumps({"access_token": jwt({"exp": 900}), "refresh_token": "refresh"}))
        self.assertTrue(tokens.access_expires_soon(now=1000))
        self.assertEqual(Tokens.from_json(tokens.to_json()), tokens)

    def test_bootstrap_does_not_send_stale_headers(self):
        client = RivianReadClient(Tokens(app_session_token="stale-app", csrf_token="stale-csrf"))
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = "https://rivian.com/api/gql/gateway/graphql"
        response.headers = {}
        response.read1.side_effect = [json.dumps({"data": {"createCsrfToken": {
            "csrfToken": "new-csrf", "appSessionToken": "new-app"
        }}}).encode(), b""]
        with mock.patch("omarivian.api._NO_REDIRECT_OPENER.open", return_value=response) as opened:
            client.create_session()
        headers = {key.lower(): value for key, value in opened.call_args.args[0].header_items()}
        for key in ("a-sess", "csrf-token", "u-sess", "authorization"):
            self.assertNotIn(key, headers)
        self.assertEqual(client.tokens.app_session_token, "new-app")
        self.assertEqual(client.tokens.csrf_token, "new-csrf")


class PollLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.raw_tokens = Tokens(access_token=jwt({"exp": 900}), refresh_token="refresh-0",
                                 user_session_token="distinct-user-session").to_json()
        self.events = []
        self.rotations = 0
        self.state = {"schemaVersion": 1, "status": "linked", "vehicles": []}
        self.vehicle_error = None
        self.refresh_error = None
        self.save_error = None
        self.auth_failures = 0
        self.start_patch("omarivian.api.time.time", side_effect=lambda: self.now)
        self.start_patch("omarivian.cli.load_tokens", side_effect=lambda: self.raw_tokens)
        self.start_patch("omarivian.cli.save_tokens", side_effect=self.save_tokens)
        self.start_patch("omarivian.cli.read_preferences", return_value={"locationEnabled": False})
        self.start_patch("omarivian.cli.write_preferences")
        self.start_patch("omarivian.cli.read_state", side_effect=lambda: copy.deepcopy(self.state))
        self.start_patch("omarivian.cli.write_state", side_effect=self.write_state)
        self.start_patch("omarivian.api.RivianReadClient._post", new=self.post)
        self.start_patch("omarivian.api.RivianReadClient.vehicles", new=self.vehicles)
        self.start_patch("omarivian.api.RivianReadClient.vehicle_artwork", return_value={})

    def start_patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def write_state(self, state):
        self.state = copy.deepcopy(state)

    def save_tokens(self, raw):
        self.events.append("save")
        if self.save_error:
            raise self.save_error
        self.raw_tokens = raw

    def post(self, operation, query, variables=None, **kwargs):
        del query, kwargs
        self.events.append(operation)
        if operation == "CreateCSRFToken":
            return {"createCsrfToken": {"csrfToken": "new-csrf", "appSessionToken": "new-app"}}
        self.assertEqual(operation, "RefreshAccessToken")
        self.assertEqual(variables, {"refreshToken": f"refresh-{self.rotations}"})
        if self.refresh_error:
            raise self.refresh_error
        self.rotations += 1
        return {"refreshAccessToken": {"accessToken": jwt({"exp": self.now + 3600}),
                                       "refreshToken": f"refresh-{self.rotations}"}}

    def vehicles(self):
        self.events.append("vehicles")
        # A fresh client is constructed from persisted credentials on every poll.
        self.assertEqual(Tokens.from_json(self.raw_tokens).user_session_token, "distinct-user-session")
        if self.auth_failures:
            self.auth_failures -= 1
            raise AuthenticationError("Rivian sign-in expired")
        if self.vehicle_error:
            raise self.vehicle_error
        return []

    def poll(self):
        return cli.command_refresh(argparse.Namespace(location=False, vehicle=None))

    def test_expired_access_renews_before_any_reads_and_rotates_on_later_polls(self):
        self.assertEqual(self.poll(), 0)
        self.assertEqual(self.events[:4], ["CreateCSRFToken", "RefreshAccessToken", "save", "vehicles"])
        self.now = 1100
        self.events.clear()
        self.assertEqual(self.poll(), 0)
        self.assertEqual(self.events, ["vehicles", "save"])
        self.now = 5000
        self.events.clear()
        self.assertEqual(self.poll(), 0)
        self.assertEqual(self.events[:4], ["CreateCSRFToken", "RefreshAccessToken", "save", "vehicles"])
        self.assertEqual(self.rotations, 2)
        self.assertEqual(Tokens.from_json(self.raw_tokens).refresh_token, "refresh-2")
        self.assertNotIn("token", json.dumps(self.state))

    def test_rotated_credentials_survive_a_later_api_failure(self):
        self.vehicle_error = ApiError("Rivian API error")
        self.assertEqual(self.poll(), 1)
        self.assertEqual(self.state["status"], "unavailable")
        self.assertEqual(Tokens.from_json(self.raw_tokens).refresh_token, "refresh-1")
        self.vehicle_error = None
        self.assertEqual(self.poll(), 0)
        self.assertEqual(self.rotations, 1)

    def test_auth_failure_after_proactive_refresh_does_not_loop(self):
        self.auth_failures = 2
        self.assertEqual(self.poll(), 2)
        self.assertEqual(self.rotations, 1)
        self.assertEqual(self.state["status"], "auth-expired")
        self.assertEqual(self.events.count("vehicles"), 1)

    def test_revoked_but_unexpired_access_still_uses_reactive_retry(self):
        tokens = Tokens.from_json(self.raw_tokens)
        tokens.access_token = jwt({"exp": 5000})
        self.raw_tokens = tokens.to_json()
        self.auth_failures = 1
        self.assertEqual(self.poll(), 0)
        self.assertEqual(self.events[:5], ["vehicles", "CreateCSRFToken", "RefreshAccessToken", "save", "vehicles"])

    def test_opaque_access_still_uses_reactive_retry(self):
        tokens = Tokens.from_json(self.raw_tokens)
        tokens.access_token = "opaque"
        self.raw_tokens = tokens.to_json()
        self.auth_failures = 1
        self.assertEqual(self.poll(), 0)
        self.assertEqual(self.rotations, 1)

    def test_valid_access_does_not_refresh_on_generic_server_failure(self):
        tokens = Tokens.from_json(self.raw_tokens)
        tokens.access_token = jwt({"exp": 5000})
        self.raw_tokens = tokens.to_json()
        self.vehicle_error = ApiError("Rivian API error")
        self.assertEqual(self.poll(), 1)
        self.assertEqual(self.rotations, 0)

    def test_refresh_rejected_retains_credentials_and_requires_link(self):
        original = self.raw_tokens
        self.refresh_error = AuthenticationError("Rivian sign-in expired")
        self.assertEqual(self.poll(), 2)
        self.assertEqual(self.raw_tokens, original)
        self.assertNotIn("vehicles", self.events)
        self.assertEqual(self.state["status"], "auth-expired")

    def test_refresh_network_failure_can_recover_on_next_poll(self):
        self.refresh_error = ApiError("Could not reach Rivian")
        self.assertEqual(self.poll(), 1)
        self.refresh_error = None
        self.assertEqual(self.poll(), 0)
        self.assertEqual(self.rotations, 1)

    def test_keyring_save_failure_stops_further_api_work(self):
        self.save_error = RuntimeError("Could not unlock or write the system keyring")
        self.assertEqual(self.poll(), 1)
        self.assertNotIn("vehicles", self.events)
        self.assertEqual(self.state["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
