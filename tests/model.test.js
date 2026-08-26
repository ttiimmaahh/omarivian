const assert = require("node:assert/strict");
const M = require("../Model.js");

const state = M.parseState(JSON.stringify({
  status: "linked",
  polledAt: "2026-08-25T12:00:00Z",
  selectedVehicleId: "two",
  locationEnabled: true,
  vehicles: [
    { id: "one", name: "R1T", battery: { percent: 72, limitPercent: 80, rangeKm: 400 }, charging: { charging: true, state: "charging", minutesRemaining: 95 }, security: { state: "locked", openClosures: [] }, climate: { cabinC: 20, active: false }, location: { latitude: 30.2672, longitude: -97.7431 } },
    { id: "two", name: "R1S", battery: {}, charging: {}, security: {}, climate: {} }
  ]
}));
assert.equal(M.statusKind(state), "ok");
assert.equal(M.selectVehicle(state, "").name, "R1S");
assert.equal(M.formatDistance(400, true), "249 mi");
assert.equal(M.formatMinutes(95), "1 h 35 min");
assert.equal(M.barLabel(state, { showChargeInBar: true }, false), "");
assert.equal(M.statusKind(M.parseState("not json")), "schema-error");
assert.match(M.mapsUrl(state.vehicles[0]), /^https:\/\/www\.openstreetmap\.org\//);
assert.equal(M.connectionLabel({ online: false, powerState: "sleeping" }), "Offline · Sleeping");
assert.equal(M.connectionLabel({ online: true, powerState: "driving" }), "Online · Driving");
assert.equal(
  M.climateLabel({ climate: { cabinC: 24.6, targetC: 24.0, active: true, mode: "heating" } }, true),
  "76°F · Heating to 75°F"
);
assert.equal(
  M.cachedStatusLabel(
    "ok",
    { polledAt: "2026-08-25T12:00:00Z" },
    { lastConnection: "2026-08-25T11:04:00Z", reportedAt: "2026-08-25T11:04:00Z" },
    "",
    Date.parse("2026-08-25T12:00:00Z")
  ),
  "Cached status · Last connected 56 min ago"
);
console.log("Model.js tests passed");
