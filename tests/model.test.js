const assert = require("node:assert/strict");
const M = require("../Model.js");

const state = M.parseState(JSON.stringify({
  status: "linked",
  polledAt: "2026-08-25T12:00:00Z",
  selectedVehicleId: "two",
  locationEnabled: true,
  vehicles: [
    { id: "one", name: "R1T", battery: { percent: 72, limitPercent: 80, rangeKm: 400 }, charging: { charging: true, state: "charging", minutesRemaining: 95 }, security: { state: "locked", openClosures: [] }, climate: { cabinC: 20, active: false }, location: { latitude: 1.25, longitude: 2.5 } },
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
// The header line is about the cloud connection alone. The activity row owns
// what the vehicle is doing, so the two lines can never contradict or repeat.
assert.equal(M.connectionLabel({ online: false, powerState: "sleeping" }), "Offline");
assert.equal(M.connectionLabel({ online: true, powerState: "driving" }), "Online");
assert.equal(M.connectionLabel(null), "—");
assert.equal(M.headerSubtitle(null), "Rivian vehicle status");
assert.equal(
  M.headerSubtitle(M.normalizeVehicle({ id: "x", name: "R1S", model: "R1S", modelYear: 2026, online: true })),
  "2026 R1S · Online"
);

// The live R2 shape: Rivian reports powerState "unknown" while the charger says
// the vehicle is plainly busy. The prominent row must follow the stronger
// signal rather than echo the weaker one.
const charging = M.normalizeVehicle({
  id: "live",
  name: "R1S",
  online: true,
  powerState: "unknown",
  battery: { percent: 64, limitPercent: 100 },
  charging: { state: "charging_active", charging: true, pluggedIn: true, minutesRemaining: 160 }
});
assert.deepEqual(M.vehicleActivity(charging), { key: "charging", label: "Charging", tone: "charging", pulse: true });
assert.equal(M.chargeEtaLabel(charging), "2 h 40 min to 100%", "the estimate must name the limit it counts down to");
assert.equal(M.chargeCaption(charging), "Limit 100%", "the caption must not repeat the activity row");
assert.equal(M.chargerLabel(charging), "Plugged in");
assert.equal(M.connectionLabel(charging), "Online");

assert.deepEqual(
  M.vehicleActivity({ online: true, powerState: "driving", charging: {} }),
  { key: "driving", label: "Driving", tone: "driving", pulse: false }
);
// The helper clears charge state once the vehicle moves, so a charging flag
// that survives into "go" is stale and must not claim the row.
assert.equal(M.vehicleActivity({ online: true, powerState: "go", charging: { charging: true } }).label, "Driving");
assert.deepEqual(
  M.vehicleActivity({ online: true, powerState: "sleeping", charging: {} }),
  { key: "sleeping", label: "Sleeping", tone: "idle", pulse: false }
);
assert.equal(M.vehicleActivity({ online: true, powerState: "sleep" }).label, "Sleeping", "the legacy R1 spelling reads the same");
assert.equal(M.vehicleActivity({ online: true, powerState: "standby" }).tone, "idle", "a resting vehicle stays visually quiet");
assert.equal(M.vehicleActivity({ online: true, powerState: "ready" }).label, "Ready");
assert.equal(M.vehicleActivity({ online: true, powerState: "unknown", charging: { pluggedIn: true } }).label, "Plugged in");
// Charging is the only state that keeps changing while you look at it, so it is
// the only one the panel is allowed to animate.
assert.equal(M.vehicleActivity({ powerState: "sleeping" }).pulse, false);
assert.equal(M.vehicleActivity({ online: true, powerState: "driving" }).pulse, false);
// With nothing but presence known, the row stays empty: the connection line
// already says Online/Offline, and "Unknown" tells the owner nothing.
assert.equal(M.vehicleActivity({ online: true, powerState: "unknown", charging: {} }).label, "");
assert.equal(M.vehicleActivity({ online: false, powerState: "" }).label, "");
assert.equal(M.vehicleActivity(null).label, "");
assert.equal(M.vehicleActivity(null).pulse, false);

assert.equal(M.chargeEtaLabel(state.vehicles[0]), "1 h 35 min to 80%");
assert.equal(
  M.chargeEtaLabel({ charging: { charging: true, minutesRemaining: 45 }, battery: {} }),
  "45 min left",
  "an unknown limit must not invent a target"
);
assert.equal(M.chargeEtaLabel({ charging: { charging: true, minutesRemaining: null }, battery: { limitPercent: 80 } }), "");
assert.equal(
  M.chargeEtaLabel({ charging: { charging: false, minutesRemaining: 30 }, battery: { limitPercent: 80 } }),
  "",
  "a countdown left over from a finished session must not show"
);
assert.equal(M.chargeEtaLabel(null), "");

assert.equal(M.chargerLabel(null), "—");
assert.equal(M.chargerLabel({ charging: { charging: false, pluggedIn: true, state: "charging_complete" } }), "Charging Complete");
assert.equal(
  M.chargerLabel({ charging: { charging: false, pluggedIn: false, state: "unknown" } }),
  "Not plugged in",
  "an unreported charger must not surface as Unknown"
);
assert.equal(M.chargerLabel({ charging: {} }), "Not plugged in");

assert.equal(M.chargeCaption({ battery: { limitPercent: 80 }, charging: {} }), "Limit 80%");
assert.equal(
  M.chargeCaption({ battery: {}, charging: { charging: true, minutesRemaining: 20 } }),
  "",
  "no limit means no caption, not a bare separator"
);
assert.equal(M.chargeCaption(null), "");

// The facts grid answers what the activity row does not: the plug, never the
// estimate, so the panel says each thing exactly once.
const facts = M.factRows(charging, { imperial: false, locationEnabled: false });
assert.deepEqual(facts.map((row) => row.label), ["Security", "Cabin", "Charger", "Location"]);
assert.equal(facts[2].value, "Plugged in");

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
