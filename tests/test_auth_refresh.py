import argparse
import unittest
from unittest import mock

import omarivian.cli as cli
from omarivian.api import AuthenticationError, RivianReadClient, Tokens


class TokenRefreshTests(unittest.TestCase):
    def test_refresh_session_rotates_access_refresh_and_user_session_tokens(self):
        client = RivianReadClient(
            Tokens(
                access_token="old-access",
                refresh_token="old-refresh",
                user_session_token="old-user-session",
                app_session_token="old-app-session",
                csrf_token="old-csrf",
            )
        )
        calls = []

        def post(operation, query, variables=None, *, authenticated=False):
            calls.append((operation, query, variables, authenticated))
            if operation == "CreateCSRFToken":
                return {
                    "createCsrfToken": {
                        "csrfToken": "new-csrf",
                        "appSessionToken": "new-app-session",
                    }
                }
            if operation == "RefreshAccessToken":
                return {
                    "refreshAccessToken": {
                        "accessToken": "new-access",
                        "refreshToken": "new-refresh",
                    }
                }
            self.fail(f"unexpected operation: {operation}")

        client._post = post
        client.refresh_session()

        self.assertEqual([call[0] for call in calls], ["CreateCSRFToken", "RefreshAccessToken"])
        self.assertEqual(calls[1][2], {"refreshToken": "old-refresh"})
        self.assertFalse(calls[1][3])
        self.assertEqual(client.tokens.access_token, "new-access")
        self.assertEqual(client.tokens.refresh_token, "new-refresh")
        self.assertEqual(client.tokens.user_session_token, "new-access")
        self.assertEqual(client.tokens.app_session_token, "new-app-session")
        self.assertEqual(client.tokens.csrf_token, "new-csrf")

    def test_command_refresh_persists_rotated_tokens_before_retry(self):
        events = []

        class FakeClient:
            def __init__(self):
                self.tokens = Tokens(
                    access_token="old-access",
                    refresh_token="old-refresh",
                    user_session_token="old-user-session",
                )
                self.vehicle_calls = 0

            def vehicles(self):
                self.vehicle_calls += 1
                events.append(f"vehicles-{self.tokens.access_token}")
                if self.vehicle_calls == 1:
                    raise AuthenticationError("Rivian sign-in expired")
                return []

            def refresh_session(self):
                events.append("refresh-session")
                self.tokens.access_token = "new-access"
                self.tokens.refresh_token = "new-refresh"
                self.tokens.user_session_token = "new-access"

            def vehicle_artwork(self, _vehicle_ids):
                return {}

        client = FakeClient()

        def save_tokens(raw):
            events.append(f"save-{Tokens.from_json(raw).access_token}")

        state = {"schemaVersion": 1, "status": "linked", "vehicles": []}
        with mock.patch.object(cli, "_load_client", return_value=client), mock.patch.object(
            cli, "read_preferences", return_value={"locationEnabled": False}
        ), mock.patch.object(cli, "write_preferences"), mock.patch.object(
            cli, "read_state", return_value=state
        ), mock.patch.object(cli, "write_state"), mock.patch.object(
            cli, "save_tokens", side_effect=save_tokens
        ):
            result = cli.command_refresh(argparse.Namespace(location=False, vehicle=None))

        self.assertEqual(result, 0)
        self.assertEqual(
            events[:4],
            [
                "vehicles-old-access",
                "refresh-session",
                "save-new-access",
                "vehicles-new-access",
            ],
        )


if __name__ == "__main__":
    unittest.main()
