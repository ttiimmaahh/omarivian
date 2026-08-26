# OmaRivian Postman workspace

This workspace mirrors the **unofficial, read-only** Rivian owner API operations used by OmaRivian. It contains no vehicle-control mutations and no credentials.

> Rivian does not publish an OAuth 2.0 authorization endpoint, token endpoint, client ID, or supported scope model for this private owner API. Labeling this as OAuth 2.0 would be misleading. The collection instead models the actual GraphQL flow: app session/CSRF creation, login or MFA, refresh-token rotation, and session headers.

## Import

Import both files into Postman:

- `OmaRivian.postman_collection.json`
- `OmaRivian.postman_environment.example.json`

Duplicate the example environment before use. Never commit or export the populated copy. Every HTTP request uses Rivian's literal HTTPS gateway URL, disables redirect following, and is rejected by a pre-request guard if the request URL changes. A variable cannot override the gateway.

## Sign in

1. Select the imported environment.
2. Fill `email` and `password` as sensitive local values.
3. Run **Authentication → Create app session**.
4. Run **Authentication → Login**.
5. If MFA is required, Login stores `otpToken`. Fill `otpCode`, then run **Login with OTP**.
6. Run **Read-only plugin operations → List vehicles**. It fills `vehicleId` with the first returned vehicle only when that variable is blank.

The response scripts store session tokens only in the selected Postman environment. Clear the environment when finished.

## Renew an expired session

1. Run **Create app session** to rotate the app-session and CSRF values.
2. Run **Refresh access token**.

Rivian rotates the refresh token. The test script immediately replaces `accessToken`, `refreshToken`, and `userSessionToken`; do not keep using an older exported environment.

## R2 Parallax WebSocket

Postman's Collection v2.1 schema represents HTTP requests, not saved WebSocket requests, so the Parallax subscription is documented here instead of being disguised as an HTTP collection item.

Create a WebSocket request in Postman with:

```text
{{websocketUrl}}
```

Headers:

```text
A-Sess: {{appSessionToken}}
U-Sess: {{userSessionToken}}
Csrf-Token: {{csrfToken}}
Apollographql-Client-Name: com.rivian.ios.consumer-apollo-ios
```

After connecting, send:

```json
{"type":"connection_init","payload":{"client-name":"com.rivian.ios.consumer-apollo-ios","client-version":"1.13.0-1494","dc-cid":"m-ios-<new UUID>","u-sess":"<userSessionToken>"}}
```

Wait for `connection_ack`, then send this read-only subscription with a fresh ID and the environment's vehicle ID substituted locally:

```json
{
  "type": "subscribe",
  "id": "<new UUID>",
  "payload": {
    "operationName": "ParallaxMessages",
    "variables": {
      "vehicleId": "<vehicleId>",
      "rvms": [
        "body.closures.states",
        "body.locks.states",
        "comfort.cabin.cabin_preconditioning_status",
        "comfort.cabin.cabin_temperatures",
        "comfort.cabin.hvac_settings_status",
        "vehicle.power.state"
      ]
    },
    "query": "subscription ParallaxMessages($vehicleId: String!, $rvms: [String!]) { parallaxMessages(vehicleId: $vehicleId, rvms: $rvms) { payload timestamp rvm } }"
  }
}
```

Location is deliberately excluded above. Add `dynamics.vehicle.gnss` only for an intentional, private diagnostic. Parallax payloads are base64-encoded protobuf and are not directly human-readable JSON.

## Data handling

- Vehicle-list responses contain full VINs.
- The optional location request returns coordinates.
- Artwork responses can contain vehicle/order identifiers.
- Never save live examples into the collection or share a populated environment.
- This is an unofficial API and may change without notice.

Reference: [Unofficial Rivian API documentation](https://rivian-api.kaedenb.org/app/parallax/domains).
