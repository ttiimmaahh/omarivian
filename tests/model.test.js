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

// The bar tooltip is drawn by an upstream Text that defaults to Text.AutoText,
// so vehicle-supplied markup would reach Qt's HTML renderer and fetch a remote
// <img>. "<" is the only character that can open a tag; entities cannot.
assert.equal(M.plainText('<img src="http://attacker/beacon.png">R1T'), 'img src="http://attacker/beacon.png">R1T');
assert.equal(M.plainText("<b>R1T</b>"), "b>R1T/b>");
assert.equal(M.plainText("Tom & Jerry"), "Tom & Jerry", "entities are inert and must survive");
assert.equal(M.plainText("R1T"), "R1T");
assert.equal(M.plainText(null), "");

const hostile = M.parseState(JSON.stringify({
  status: "linked",
  polledAt: "2026-08-25T12:00:00Z",
  selectedVehicleId: "one",
  vehicles: [
    { id: "one", name: '<img src="http://attacker/beacon.png">R1T', battery: { percent: 50, rangeKm: 100 }, charging: {}, security: {}, climate: {} }
  ]
}));
const tip = M.tooltipText(hostile, { unit: "metric" }, Date.parse("2026-08-25T12:00:00Z"));
assert.ok(!tip.includes("<"), "tooltip text must not carry a tag opener into an AutoText renderer");
assert.ok(tip.includes("beacon.png"), "sanitising must not silently drop the rest of the name");

const broken = M.parseState("not json");
assert.ok(!M.tooltipText(broken, {}, Date.now()).includes("<"));

console.log("Model.js tests passed");
