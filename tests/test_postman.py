import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COLLECTION = ROOT / "postman" / "OmaRivian.postman_collection.json"
ENVIRONMENT = ROOT / "postman" / "OmaRivian.postman_environment.example.json"
GATEWAY = "https://rivian.com/api/gql/gateway/graphql"
AUTH_MUTATIONS = {
    "CreateCSRFToken",
    "Login",
    "LoginWithOTP",
    "RefreshAccessToken",
}
SECRET_KEYS = {
    "email",
    "password",
    "otpCode",
    "otpToken",
    "csrfToken",
    "appSessionToken",
    "accessToken",
    "refreshToken",
    "userSessionToken",
    "vehicleId",
}


def _requests(nodes):
    for node in nodes:
        if "request" in node:
            yield node
        yield from _requests(node.get("item", []))


class PostmanTests(unittest.TestCase):
    def test_requests_use_literal_gateway_and_reject_redirects(self):
        collection = json.loads(COLLECTION.read_text())
        requests = list(_requests(collection["item"]))

        self.assertEqual(len(requests), 8)
        self.assertTrue(all(item["request"]["url"] == GATEWAY for item in requests))
        self.assertTrue(
            all(
                item.get("protocolProfileBehavior", {}).get("followRedirects") is False
                for item in requests
            )
        )
        script = "\n".join(collection["event"][0]["script"]["exec"])
        self.assertIn("pm.request.url.toString()", script)
        self.assertNotIn("pm.environment.get", script)
        self.assertNotIn("{{gatewayUrl}}", COLLECTION.read_text())

    def test_collection_contains_only_auth_mutations_and_read_queries(self):
        collection = json.loads(COLLECTION.read_text())
        operations = []
        for item in _requests(collection["item"]):
            body = json.loads(item["request"]["body"]["raw"])
            operations.append((body["operationName"], body["query"].lstrip()))

        mutations = {name for name, query in operations if query.startswith("mutation ")}
        non_auth_mutations = {
            name for name, query in operations
            if query.startswith("mutation ") and name not in AUTH_MUTATIONS
        }
        self.assertEqual(mutations, AUTH_MUTATIONS)
        self.assertEqual(non_auth_mutations, set())

    def test_refresh_rotates_access_and_refresh_but_preserves_user_session(self):
        collection = json.loads(COLLECTION.read_text())
        refresh = next(
            item for item in _requests(collection["item"])
            if json.loads(item["request"]["body"]["raw"])["operationName"]
            == "RefreshAccessToken"
        )
        script = "\n".join(refresh["event"][0]["script"]["exec"])

        self.assertIn('pm.environment.set("accessToken"', script)
        self.assertIn('pm.environment.set("refreshToken"', script)
        self.assertNotIn('pm.environment.set("userSessionToken"', script)
        self.assertNotIn('pm.environment.unset("userSessionToken"', script)

    def test_example_environment_contains_no_secrets_or_gateway_override(self):
        environment = json.loads(ENVIRONMENT.read_text())
        values = {item["key"]: item["value"] for item in environment["values"]}

        self.assertNotIn("gatewayUrl", values)
        self.assertTrue(SECRET_KEYS.issubset(values))
        self.assertTrue(all(values[key] == "" for key in SECRET_KEYS))


if __name__ == "__main__":
    unittest.main()
