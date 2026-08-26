// Pure, dependency-free helpers for the OmaRivian panel.
// Every function tolerates malformed input so a bad state file degrades into a
// readable panel instead of a QML exception. Also loadable from Node for tests.

var KM_TO_MI = 0.621371;

function isObject(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }
function num(v) { return (typeof v === "number" && Number.isFinite(v)) ? v : null; }
function text(v) { return (typeof v === "string" && v.length > 0) ? v : ""; }
function flag(v) { return v === true; }
function dash(v) { return (v === null || v === undefined || v === "") ? "—" : v; }
function imperial(settings, localeName) {
  if (isObject(settings) && settings.unit === "imperial") return true;
  if (isObject(settings) && settings.unit === "metric") return false;
  return /^en[_-]US($|[_.-])/.test(String(localeName || "").replace(".", "_"));
}
function join(parts, sep) { return parts.filter((p) => text(p)).join(sep); }

function refreshIntervalSec(settings) {
  var n = isObject(settings) ? num(settings.refreshIntervalSec) : null;
  return Math.max(300, n === null ? 900 : Math.round(n));
}

function normalizeVehicle(raw) {
  if (!isObject(raw)) return null;
  var id = text(raw.id);
  if (!id) return null;
  var b = isObject(raw.battery) ? raw.battery : {};
  var c = isObject(raw.charging) ? raw.charging : {};
  var s = isObject(raw.security) ? raw.security : {};
  var cl = isObject(raw.climate) ? raw.climate : {};
  var loc = isObject(raw.location) ? raw.location : null;
  var lat = loc ? num(loc.latitude) : null;
  var lon = loc ? num(loc.longitude) : null;
  return {
    id: id,
    name: text(raw.name) || "Rivian",
    model: text(raw.model),
    modelYear: num(raw.modelYear),
    vinSuffix: text(raw.vinSuffix),
    reportedAt: text(raw.reportedAt),
    online: flag(raw.online),
    powerState: text(raw.powerState),
    battery: { percent: num(b.percent), limitPercent: num(b.limitPercent), rangeKm: num(b.rangeKm) },
    charging: {
      state: text(c.state), charging: flag(c.charging),
      pluggedIn: flag(c.pluggedIn), minutesRemaining: num(c.minutesRemaining)
    },
    security: {
      state: text(s.state),
      openClosures: Array.isArray(s.openClosures)
        ? s.openClosures.filter((x) => text(x)) : []
    },
    climate: { cabinC: num(cl.cabinC), active: flag(cl.active), mode: text(cl.mode) },
    location: normalizeLocation(loc, lat, lon),
    odometerKm: num(raw.odometerKm),
    softwareVersion: text(raw.softwareVersion),
    lastConnection: text(raw.lastConnection)
  };
}

function normalizeLocation(loc, lat, lon) {
  if (lat === null || lon === null) return null;
  return { latitude: lat, longitude: lon, reportedAt: loc ? text(loc.reportedAt) : "" };
}

function emptyState(status, message) {
  return {
    status: text(status) || "loading", message: text(message), polledAt: "",
    selectedVehicleId: "", locationEnabled: false, vehicles: []
  };
}

function normalizeState(raw) {
  if (!isObject(raw)) return emptyState("schema-error", "State file has an unexpected shape.");
  var list = Array.isArray(raw.vehicles) ? raw.vehicles : [];
  var vehicles = [];
  for (var i = 0; i < list.length; i++) {
    var v = normalizeVehicle(list[i]);
    if (v) vehicles.push(v);
  }
  return {
    status: text(raw.status) || (vehicles.length > 0 ? "ok" : "unavailable"),
    message: text(raw.message),
    polledAt: text(raw.polledAt),
    selectedVehicleId: text(raw.selectedVehicleId),
    locationEnabled: flag(raw.locationEnabled),
    vehicles: vehicles
  };
}

function parseState(body) {
  if (typeof body !== "string" || body.trim().length === 0)
    return emptyState("loading", "Waiting for the first refresh.");
  try {
    return normalizeState(JSON.parse(body));
  } catch (error) {
    if (error) return emptyState("schema-error", "State file is not valid JSON.");
    return emptyState("schema-error", "State file is not valid JSON.");
  }
}

// One of: loading | unlinked | auth-expired | schema-error | unavailable | ok
function statusKind(state) {
  var s = (state && typeof state.status === "string") ? state.status.toLowerCase() : "";
  if (s.includes("unlink") || s.includes("no_account") || s.includes("not_linked")) return "unlinked";
  if (s.includes("auth") || s.includes("token") || s.includes("otp")) return "auth-expired";
  if (s.includes("schema") || s.includes("parse")) return "schema-error";
  if (s === "loading" || s === "pending" || s === "") return "loading";
  if (s === "ok" || s === "linked" || s === "ready" || s === "success") return "ok";
  return "unavailable";
}

function statusBanner(kind, state) {
  var msg = (state && text(state.message)) || "";
  if (kind === "unlinked") return { title: "Not linked", detail: msg || "Link your Rivian account to see vehicle status." };
  if (kind === "auth-expired") return { title: "Sign-in expired", detail: msg || "Rivian rejected the saved session. Link again to continue." };
  if (kind === "schema-error") return { title: "Unreadable state", detail: msg || "The state file could not be understood." };
  if (kind === "unavailable") return { title: "Status unavailable", detail: msg || "Rivian did not return vehicle data." };
  if (kind === "loading") return { title: "Loading", detail: msg || "Fetching vehicle status…" };
  return { title: "", detail: msg };
}

function selectVehicle(state, overrideId) {
  if (!state || !Array.isArray(state.vehicles) || state.vehicles.length === 0) return null;
  var wanted = text(overrideId) || text(state.selectedVehicleId);
  for (var i = 0; i < state.vehicles.length; i++)
    if (state.vehicles[i].id === wanted) return state.vehicles[i];
  return state.vehicles[0];
}

function titleCase(s) {
  if (!text(s)) return "";
  return s.replace(/[_-]+/g, " ").toLowerCase().replace(/\b[a-z]/g, (m) => m.toUpperCase());
}

function vehicleTitle(v) { return v ? (v.name || "Rivian") : "Vehicle"; }
function vehicleSubtitle(v) {
  if (!v) return "";
  return join([v.modelYear === null ? "" : String(Math.round(v.modelYear)), v.model], " ");
}
function connectionLabel(v) {
  if (!v) return "—";
  return join([v.online ? "Online" : "Offline", titleCase(v.powerState)], " · ");
}

function formatPercent(n) { return num(n) === null ? "—" : Math.round(n) + "%"; }

function formatDistance(km, useImperial) {
  var n = num(km);
  if (n === null) return "—";
  return useImperial ? Math.round(n * KM_TO_MI) + " mi" : Math.round(n) + " km";
}

function formatOdometer(km, useImperial) {
  var n = num(km);
  if (n === null) return "—";
  var v = String(Math.round(useImperial ? n * KM_TO_MI : n)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return v + (useImperial ? " mi" : " km");
}

function formatTemp(c, useImperial) {
  var n = num(c);
  if (n === null) return "—";
  return useImperial ? Math.round(n * 9 / 5 + 32) + "°F" : Math.round(n) + "°C";
}

function formatMinutes(m) {
  var n = num(m);
  if (n === null || n < 0) return "";
  var mins = Math.round(n);
  if (mins < 60) return mins + " min";
  var h = Math.floor(mins / 60), rem = mins % 60;
  return rem === 0 ? h + " h" : h + " h " + rem + " min";
}

function parseTime(iso) {
  if (!text(iso)) return null;
  var t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}

function formatAge(iso, nowMs) {
  var t = parseTime(iso);
  if (t === null) return "—";
  var secs = Math.max(0, Math.round(((num(nowMs) === null ? Date.now() : nowMs) - t) / 1000));
  if (secs < 90) return "just now";
  if (secs < 3600) return Math.round(secs / 60) + " min ago";
  if (secs < 86400) return Math.round(secs / 3600) + " h ago";
  return Math.round(secs / 86400) + " d ago";
}

// Staleness follows the vehicle's own timestamp, not merely a successful poll.
function isStale(state, nowMs, intervalSec) {
  var vehicle = selectVehicle(state, "");
  var reported = vehicle ? (vehicle.reportedAt || vehicle.lastConnection) : "";
  var t = parseTime(reported);
  if (t === null) return false;
  var limit = refreshIntervalSec({ refreshIntervalSec: intervalSec }) * 2000;
  return ((num(nowMs) === null ? Date.now() : nowMs) - t) > limit;
}

function cachedStatusLabel(kind, state, vehicle, helperError, nowMs) {
  if (text(helperError)) return "Refresh failed · Showing cached data";
  if (kind !== "ok") {
    var title = statusBanner(kind, state).title || "Status unavailable";
    return title + " · Showing cached data";
  }
  var timestamp = vehicle ? (vehicle.lastConnection || vehicle.reportedAt) : "";
  var age = formatAge(timestamp, nowMs);
  return "Cached status" + (age === "—" ? "" : " · Last connected " + age);
}

function chargingLabel(v) {
  if (!v) return "—";
  var c = v.charging, state = titleCase(c.state);
  if (c.charging) {
    var eta = formatMinutes(c.minutesRemaining);
    return join([state || "Charging", eta ? eta + " left" : ""], " · ");
  }
  return state || (c.pluggedIn ? "Plugged in" : "Not plugged in");
}

function securityLabel(v) {
  if (!v) return "—";
  var open = v.security.openClosures;
  if (open.length > 0) return open.map(titleCase).join(", ") + " open";
  return titleCase(v.security.state) || "Secured";
}

function climateLabel(v, useImperial) {
  if (!v) return "—";
  var cabin = formatTemp(v.climate.cabinC, useImperial);
  if (!v.climate.active) return cabin;
  return cabin + " · " + (titleCase(v.climate.mode) || "Conditioning");
}

function roundCoord(n, digits) {
  var v = num(n);
  if (v === null) return null;
  var f = 10 ** (num(digits) === null ? 4 : digits);
  return Math.round(v * f) / f;
}

function coordText(v) {
  if (!v || !v.location) return "";
  return roundCoord(v.location.latitude, 4) + ", " + roundCoord(v.location.longitude, 4);
}

function mapsUrl(v) {
  if (!v || !v.location) return "";
  var lat = roundCoord(v.location.latitude, 5), lon = roundCoord(v.location.longitude, 5);
  return "https://www.openstreetmap.org/?mlat=" + lat + "&mlon=" + lon + "#map=15/" + lat + "/" + lon;
}

function locationLabel(v, locationEnabled) {
  if (!locationEnabled) return "Disabled in settings";
  if (!v || !v.location) return "Not reported";
  return coordText(v);
}

function factRows(v, opts) {
  var o = isObject(opts) ? opts : {};
  return [
    { label: "Security", value: securityLabel(v) },
    { label: "Cabin", value: climateLabel(v, flag(o.imperial)) },
    { label: "Charging", value: chargingLabel(v) },
    { label: "Location", value: locationLabel(v, flag(o.locationEnabled)) }
  ];
}

function detailRows(v, opts) {
  var o = isObject(opts) ? opts : {};
  return [
    { label: "Odometer", value: v ? formatOdometer(v.odometerKm, flag(o.imperial)) : "—" },
    { label: "Software", value: v ? dash(v.softwareVersion) : "—" },
    { label: "Last connection", value: v ? formatAge(v.lastConnection || v.reportedAt, o.nowMs) : "—" },
    { label: "VIN suffix", value: (v && v.vinSuffix) ? "…" + v.vinSuffix : "—" },
    { label: "Polled", value: formatAge(o.polledAt, o.nowMs) }
  ];
}

function chargeCaption(v) {
  if (!v) return "";
  var limit = v.battery.limitPercent;
  return join([limit === null ? "" : "Limit " + formatPercent(limit), chargingLabel(v)], " · ");
}

function headerSubtitle(v) {
  return v ? join([vehicleSubtitle(v), connectionLabel(v)], " · ") : "Rivian vehicle status";
}

// 0..1 clamped fraction for the charge track and its limit marker.
function fraction(percent) {
  var n = num(percent);
  return n === null ? 0 : Math.max(0, Math.min(1, n / 100));
}

function barLabel(state, settings, horizontal) {
  if (!horizontal || !isObject(settings) || settings.showChargeInBar !== true) return "";
  var v = selectVehicle(state, "");
  return (v && v.battery.percent !== null) ? formatPercent(v.battery.percent) : "";
}

function tooltipText(state, settings, nowMs) {
  var kind = statusKind(state);
  if (kind !== "ok") return "OmaRivian · " + statusBanner(kind, state).title;
  var v = selectVehicle(state, "");
  if (!v) return "OmaRivian";
  return vehicleTitle(v) + " · " + formatPercent(v.battery.percent) + " · "
    + formatDistance(v.battery.rangeKm, imperial(settings, settings ? settings.localeName : ""))
    + "\nUpdated " + formatAge(state.polledAt, nowMs);
}

if (typeof module === "object" && module !== null && module.exports) {
  module.exports = {
    barLabel: barLabel, cachedStatusLabel: cachedStatusLabel, chargeCaption: chargeCaption,
    chargingLabel: chargingLabel, climateLabel: climateLabel,
    connectionLabel: connectionLabel, coordText: coordText, detailRows: detailRows, emptyState: emptyState,
    factRows: factRows, formatAge: formatAge, formatDistance: formatDistance, formatMinutes: formatMinutes,
    formatOdometer: formatOdometer, formatPercent: formatPercent, formatTemp: formatTemp, fraction: fraction,
    headerSubtitle: headerSubtitle, imperial: imperial, isStale: isStale, locationLabel: locationLabel,
    mapsUrl: mapsUrl, normalizeState: normalizeState, normalizeVehicle: normalizeVehicle, parseState: parseState,
    refreshIntervalSec: refreshIntervalSec, roundCoord: roundCoord, securityLabel: securityLabel,
    selectVehicle: selectVehicle, statusBanner: statusBanner, statusKind: statusKind, titleCase: titleCase,
    tooltipText: tooltipText, vehicleSubtitle: vehicleSubtitle, vehicleTitle: vehicleTitle
  };
}
