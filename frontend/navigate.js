/* wardrivrr navigate — MapLibre pitch HUD + sim GPS + explorer + auto-level */

const STYLE_NIGHT = "https://tiles.openfreemap.org/styles/dark";
const STYLE_DAY = "https://tiles.openfreemap.org/styles/liberty";
const PITCH_3D = 50;
const PITCH_2D = 0;
const VIEW_3D_KEY = "wardrivrr_nav_3d";
/** @deprecated kept for one-time migration from buildings-only pref */
const BUILDINGS_KEY = "wardrivrr_nav_buildings";
const DEAD_ENDS_KEY = "wardrivrr_nav_exclude_dead_ends";

const CAM_MS = 32;
/** Smooth follow time-constant (higher = snappier) */
const CAM_SMOOTH = 7.5;
const BEARING_SMOOTH = 5.5;
const ZOOM_SMOOTH = 4.0;
/** After pan/rotate, wait this long before GPS pulls the camera back */
const USER_CAM_COOLDOWN_MS = 3000;
/**
 * Re-follow after a user pan/rotate: accelerate to mid-gap, then decelerate.
 * Phase 1 = XY only; phase 2 (marker within CATCH_ALIGN_M) = zoom + bearing too.
 */
const CATCH_K_START = 3.5; // leave the panned/rotated view
const CATCH_K_PEAK = 11; // fastest at half gap
const CATCH_K_END = 6.5; // final approach — brisk, not a crawl
/** Start zoom + bearing once camera center is this close to the marker */
const CATCH_ALIGN_M = 110;
const CATCH_LOCK_M = 0.15;
const CATCH_LOCK_DEG = 0.8;
/** Drift threshold to start a catch-up without a gesture */
const CATCH_RESUME_M = 12;

/** Closest street-level default; speed / next-turn pull out within these caps */
const ZOOM_DEFAULT = 17.8;
const ZOOM_MAX = 18.6; // crawl / at turn
const ZOOM_MIN = 15.2; // fast drive ceiling (never farther than this)
const ZOOM_SPEED_REF_KMH = 90; // at/above → ZOOM_MIN from speed alone
const ZOOM_TURN_NEAR_M = 60;
const ZOOM_TURN_FAR_M = 350;
/** GPS push while driving */
const FIX_MS = 2500;
/** Stationary: keep session alive without hammering API / waking the map */
const FIX_MS_IDLE = 20000;
const OUTSIDE_TRIGGER_M = 300;
const YES_FILL_MS = 20000;
const CONTAINS_MS = 2000;
/** Outside-level poll when parked (distance can't change without moving) */
const CONTAINS_MS_IDLE = 12000;
/** Parked-but-spawned tick — enough for rare GPS keep-alive, not a render loop */
const IDLE_TICK_MS = 1000;
/**
 * Client HUD: snap icon onto active Valhalla route when within this many meters.
 * Backend fog unlock uses GPS_SNAP_THRESHOLD_M (default 8, max 10) on road_segments —
 * keep these in the same ballpark so rail lag still sticks to the road.
 */
const SNAP_TO_ROAD_M = 8;
/** Soft leave corridor — hide TBT, keep route, try to rejoin */
const OFF_ROUTE_M = 45;
/** Only full replan after this far from the last on-route point */
const REROUTE_FROM_LAST_GOOD_M = 80;
const REPLAN_COOLDOWN_MS = 4000;
/** Facing against the line counts as “not correct” (same rejoin/reroute rules) */
const WRONG_WAY_DEG = 110;
/** Require this many consecutive bad fixes before divert / replan (gpsd lag) */
const WRONG_WAY_STREAK_N = 10;
/** Ignore heading disagreement when nearly stopped (track is junk) */
const WRONG_WAY_MIN_SPEED_KMH = 3;
const AUTO_EXPLORE_RETRY_BASE_MS = 2000;
const AUTO_EXPLORE_RETRY_MAX_MS = 30000;

const DEBUG_NAV =
  typeof location !== "undefined" &&
  new URLSearchParams(location.search).get("debug") === "1";

const state = {
  map: null,
  marker: null,
  levelId: null,
  levelName: "—",
  levelBoundary: null,
  spawned: false,
  spawnMode: false,
  lat: 51.286,
  lon: 7.293,
  heading: 0,
  speedKmh: 0,
  keys: new Set(),
  route: null,
  routeGeo: null,
  sessionUnlockM: 0,
  sessionStartedAt: null,
  buildingsOn: false,
  /** True = pitched 3D + extruded buildings; false = flat 2D */
  view3d: true,
  /** Turn-by-turn / explore active — area prompts only while true */
  navigationActive: false,
  excludeDeadEnds: false,
  camLat: null,
  camLon: null,
  camBearing: 0,
  camPitch: PITCH_3D,
  camZoom: ZOOM_DEFAULT,
  /** Smoothed pose for the chevron (lerped every rAF toward GPS/sim) */
  dispLat: null,
  dispLon: null,
  dispHeading: 0,
  lastDispAt: 0,
  /** performance.now() until which user map gestures own the camera */
  userCamUntil: 0,
  userCamActive: false,
  /** Press paused follow; true until drag/rotate finalizes cooldown length */
  userCamGesturePending: false,
  /** True while easing camera back to the chevron after a user pan */
  camCatchingUp: false,
  /** Distance (m) when the current catch-up began — drives accel/decel split */
  catchOriginDistM: 0,
  catchOriginBrgErr: 0,
  /** Ignore map gesture events while we jumpTo/ease programmatically */
  camProgrammatic: false,
  webglOk: false,
  night: null,
  moving: false,
  pushInFlight: false,
  exploreInFlight: false,
  diverted: false,
  lastGoodLat: null,
  lastGoodLon: null,
  lastReplanAt: 0,
  lastCam: 0,
  lastFix: 0,
  lastContains: 0,
  lastSpeedUi: -1,
  outsideM: 0,
  lastOutsideLat: null,
  lastOutsideLon: null,
  promptOpen: false,
  promptSuggestion: null,
  promptTimer: null,
  promptFillStart: 0,
  dismissedLabel: null,
  containsInFlight: false,
  building: false,
  anomalyAlerts: true,
  anomalyAlerted: new Set(),
  anomalyLastToastAt: 0,
  /** Page/map visible and sim loop allowed to run */
  simActive: true,
  /** True while WASD/turning or speed ≠ 0 — drives adaptive quality */
  driveHot: false,
  rafId: 0,
  idleTimer: 0,
  lastFrameAt: 0,
  /** Follow GPS posted by gpsd poller or tools/drive_sim (source=gpsd|client) */
  followLiveGps: false,
  followInFlight: false,
  lastFollowAt: 0,
  wrongWayStreak: 0,
  offRouteStreak: 0,
  autoExploreStarted: false,
  autoExploreAttempts: 0,
  autoExploreRetryAt: 0,
  achievementSounds: true,
  gpsSource: null,
};

/** Poll gpsd-backed fix often enough to feed the rAF lerp (backend ~5 Hz) */
const FOLLOW_MS = 200;

const ANOMALY_COOLDOWN_MS = 12000;

function supportsWebGL() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

function haversineM(lat1, lon1, lat2, lon2) {
  const r = 6371000;
  const toR = Math.PI / 180;
  const dLat = (lat2 - lat1) * toR;
  const dLon = (lon2 - lon1) * toR;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * toR) * Math.cos(lat2 * toR) * Math.sin(dLon / 2) ** 2;
  return 2 * r * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** Discrete distance buckets (meters), largest first; below 20 → "now" */
const DIST_BUCKETS_M = [
  1000, 800, 600, 500, 400, 300, 250, 200, 150, 100, 80, 60, 50, 40, 30, 20,
];

/** @returns {{ value: string, unit: string }} */
function fmtMetersParts(m) {
  if (m == null || !Number.isFinite(m)) return { value: "—", unit: "" };
  if (m < 20) return { value: "now", unit: "" };
  if (m > 1000) {
    return {
      value: (Math.ceil(m / 100) / 10).toFixed(1),
      unit: "km",
    };
  }
  for (let i = DIST_BUCKETS_M.length - 1; i >= 0; i--) {
    const b = DIST_BUCKETS_M[i];
    if (m <= b) {
      if (b >= 1000) return { value: "1.0", unit: "km" };
      return { value: String(b), unit: "m" };
    }
  }
  return { value: "1.0", unit: "km" };
}

function fmtMeters(m) {
  const p = fmtMetersParts(m);
  if (!p.unit) return p.value;
  return `${p.value} ${p.unit}`;
}

function isContinueManeuver(m) {
  const t = Number(m?.type);
  // start / continue / bearon — not the turn we count down to
  return [1, 2, 3, 7, 8, 17, 18, 25, 29].includes(t);
}

/** Next real turn ahead of shape index (skip continue/start). */
function nextTurnManeuver(mans, shapeIdx) {
  if (!mans?.length) return null;
  for (let i = 0; i < mans.length; i++) {
    const end = mans[i].end_shape_index ?? mans[i].begin_shape_index ?? 0;
    if (end < shapeIdx) continue;
    if (isContinueManeuver(mans[i])) continue;
    return mans[i];
  }
  return mans[mans.length - 1] || null;
}

/** Metres along the route to the next real turn, or null if no active route. */
function nextTurnDistanceM() {
  const route = state.route;
  const coords = route?.geometry?.coordinates;
  if (!route || !coords?.length || state.diverted) return null;
  const idx = nearestShapeIndex(coords, state.lon, state.lat);
  const mans = route.maneuvers || [];
  const next = nextTurnManeuver(mans, idx) || route.next || mans[0];
  if (!next) return null;
  const begin = next.begin_shape_index ?? idx;
  const end = next.end_shape_index ?? begin;
  const target = idx < begin ? begin : Math.max(idx, end);
  return pathMeters(coords, idx, target);
}

/**
 * Target map zoom from speed (+ next-turn when navigating).
 * Higher zoom = closer. Capped to [ZOOM_MIN, ZOOM_MAX].
 */
function targetZoom() {
  const speed = Math.max(0, Number(state.speedKmh) || 0);
  const speedT = Math.min(1, speed / ZOOM_SPEED_REF_KMH);
  // Slow → close (ZOOM_MAX); fast → pulled out toward ZOOM_MIN
  let z = ZOOM_MAX - speedT * (ZOOM_MAX - ZOOM_MIN);

  if (state.navigationActive) {
    const dist = nextTurnDistanceM();
    if (dist != null && dist < ZOOM_TURN_FAR_M) {
      const span = Math.max(1, ZOOM_TURN_FAR_M - ZOOM_TURN_NEAR_M);
      const nearT = 1 - Math.min(1, Math.max(0, dist - ZOOM_TURN_NEAR_M) / span);
      // Pull toward ZOOM_MAX as the turn approaches
      z += (ZOOM_MAX - z) * nearT;
    }
  }

  return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
}

/**
 * Turn glyphs — driver at bottom, looking up. Padded 80×80 viewBox so thick
 * strokes don't clip or look like the opposite bend when scaled up.
 */
function maneuverIconSvg(m) {
  const type = Number(m?.type);
  let kind = "straight";
  if ([4, 5, 6].includes(type)) kind = "dest";
  else if ([9, 19, 21, 23].includes(type)) kind = "slight-right";
  else if ([10].includes(type)) kind = "right";
  else if ([11].includes(type)) kind = "sharp-right";
  else if ([16, 20, 22, 24].includes(type)) kind = "slight-left";
  else if ([15].includes(type)) kind = "left";
  else if ([14].includes(type)) kind = "sharp-left";
  else if ([12].includes(type)) kind = "uturn-right";
  else if ([13].includes(type)) kind = "uturn-left";
  else if ([26].includes(type)) kind = "merge-right";
  else if ([27, 28].includes(type)) kind = "roundabout";

  const stroke =
    'class="nav-turn-stroke" fill="none" stroke="currentColor" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"';
  const head = 'class="nav-turn-head" fill="currentColor"';

  const icons = {
    straight: `
      <path ${stroke} d="M40 68 V22"/>
      <path ${head} d="M40 10 L52 28 H28 Z"/>`,
    right: `
      <path ${stroke} d="M40 68 V40 H64"/>
      <path ${head} d="M72 40 L54 28 V52 Z"/>`,
    left: `
      <path ${stroke} d="M40 68 V40 H16"/>
      <path ${head} d="M8 40 L26 28 V52 Z"/>`,
    "slight-right": `
      <path ${stroke} d="M40 68 V44 L58 22"/>
      <path ${head} d="M64 14 L66 32 L48 26 Z"/>`,
    "slight-left": `
      <path ${stroke} d="M40 68 V44 L22 22"/>
      <path ${head} d="M16 14 L32 26 L14 32 Z"/>`,
    "sharp-right": `
      <path ${stroke} d="M40 68 V46 L62 58"/>
      <path ${head} d="M70 62 L52 50 L58 72 Z"/>`,
    "sharp-left": `
      <path ${stroke} d="M40 68 V46 L18 58"/>
      <path ${head} d="M10 62 L28 50 L22 72 Z"/>`,
    "uturn-right": `
      <path ${stroke} d="M28 68 V34 A12 12 0 0 1 52 34 V52"/>
      <path ${head} d="M52 64 L40 52 H64 Z"/>`,
    "uturn-left": `
      <path ${stroke} d="M52 68 V34 A12 12 0 0 0 28 34 V52"/>
      <path ${head} d="M28 64 L40 52 H16 Z"/>`,
    "merge-right": `
      <path ${stroke} d="M30 68 V40 L54 18"/>
      <path ${head} d="M60 10 L62 28 L44 22 Z"/>`,
    dest: `
      <path ${stroke} d="M40 68 V30"/>
      <circle class="nav-turn-dot" fill="currentColor" cx="40" cy="18" r="10"/>`,
    roundabout: `
      <path ${stroke} d="M40 68 V52"/>
      <circle ${stroke} cx="40" cy="36" r="14"/>
      <path ${stroke} d="M54 36 H66"/>
      <path ${head} d="M74 36 L58 26 V46 Z"/>`,
  };

  const body = icons[kind] || icons.straight;
  return `<svg viewBox="0 0 80 80" width="100%" height="100%" aria-hidden="true">${body}</svg>`;
}

function setManeuverIcon(el, m) {
  if (!el) return;
  if (!m) {
    el.innerHTML = `<svg viewBox="0 0 80 80" width="100%" height="100%" aria-hidden="true"><circle class="nav-turn-dot" fill="currentColor" cx="40" cy="40" r="8"/></svg>`;
    return;
  }
  el.innerHTML = maneuverIconSvg(m);
}

function maneuverVerb(m) {
  if (!m) return "Continue";
  const type = Number(m.type);
  const map = {
    1: "Start",
    2: "Start",
    3: "Start",
    4: "Destination",
    5: "Destination",
    6: "Destination",
    7: "Continue",
    8: "Continue",
    9: "Slight right",
    10: "Right",
    11: "Sharp right",
    12: "U-turn",
    13: "U-turn",
    14: "Sharp left",
    15: "Left",
    16: "Slight left",
    17: "Continue",
    26: "Merge",
    27: "Roundabout",
    28: "Exit roundabout",
  };
  return map[type] || "Continue";
}

function nearestShapeIndex(coords, lon, lat) {
  let best = 0;
  let bestD = Infinity;
  for (let i = 0; i < coords.length; i++) {
    const d = haversineM(lat, lon, coords[i][1], coords[i][0]);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

function pathMeters(coords, fromIdx, toIdx) {
  let m = 0;
  const a = Math.max(0, fromIdx);
  const b = Math.min(coords.length - 1, toIdx);
  for (let i = a; i < b; i++) {
    m += haversineM(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0]);
  }
  return m;
}

/** Distance from GPS to a polyline segment (meters, local ENU). */
function distPointToSegM(lat, lon, lat1, lon1, lat2, lon2) {
  const mx = 111320 * Math.cos((lat * Math.PI) / 180);
  const my = 111320;
  const ax = (lon1 - lon) * mx;
  const ay = (lat1 - lat) * my;
  const bx = (lon2 - lon) * mx;
  const by = (lat2 - lat) * my;
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t =
    len2 < 1e-9 ? 0 : Math.max(0, Math.min(1, (-ax * dx - ay * dy) / len2));
  return Math.hypot(ax + t * dx, ay + t * dy);
}

function distToRouteM(lon, lat, coords) {
  return closestOnRoute(lon, lat, coords).distM;
}

/** Nearest point on route polyline (local ENU). */
function closestOnRoute(lon, lat, coords) {
  if (!coords?.length) {
    return { lon, lat, distM: Infinity, t: 0, seg: -1 };
  }
  if (coords.length === 1) {
    return {
      lon: coords[0][0],
      lat: coords[0][1],
      distM: haversineM(lat, lon, coords[0][1], coords[0][0]),
      t: 0,
      seg: 0,
    };
  }
  const mx = 111320 * Math.cos((lat * Math.PI) / 180);
  const my = 111320;
  const near = nearestShapeIndex(coords, lon, lat);
  const i0 = Math.max(0, near - 12);
  const i1 = Math.min(coords.length - 2, near + 12);
  let best = { lon, lat, distM: Infinity, t: 0, seg: -1 };
  for (let i = i0; i <= i1; i++) {
    const lon1 = coords[i][0];
    const lat1 = coords[i][1];
    const lon2 = coords[i + 1][0];
    const lat2 = coords[i + 1][1];
    const ax = (lon1 - lon) * mx;
    const ay = (lat1 - lat) * my;
    const bx = (lon2 - lon) * mx;
    const by = (lat2 - lat) * my;
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 < 1e-9 ? 0 : Math.max(0, Math.min(1, (-ax * dx - ay * dy) / len2));
    const distM = Math.hypot(ax + t * dx, ay + t * dy);
    if (distM < best.distM) {
      best = {
        lon: lon1 + t * (lon2 - lon1),
        lat: lat1 + t * (lat2 - lat1),
        distM,
        t,
        seg: i,
      };
    }
  }
  return best;
}

/**
 * If GPS is within SNAP_TO_ROAD_M of the active route, snap for icon /
 * camera / off-route. Beyond threshold: leave as-is (no wild jump).
 */
function applyRouteSnap(rawLon, rawLat) {
  const coords = state.route?.geometry?.coordinates;
  if (!coords?.length || state.diverted) {
    return { lon: rawLon, lat: rawLat, snapped: false, distM: null };
  }
  const hit = closestOnRoute(rawLon, rawLat, coords);
  if (hit.distM <= SNAP_TO_ROAD_M) {
    return {
      lon: hit.lon,
      lat: hit.lat,
      snapped: true,
      distM: hit.distM,
    };
  }
  return { lon: rawLon, lat: rawLat, snapped: false, distM: hit.distM };
}

/** Apply server-snapped fix, then optional route polish for the icon. */
function applyDisplayPosition(lon, lat) {
  const local = applyRouteSnap(lon, lat);
  state.lon = local.lon;
  state.lat = local.lat;
  return local;
}

function clearManeuverHud() {
  const side = document.querySelector(".nav-hud-side");
  if (side) side.hidden = true;
  const next = document.getElementById("maneuverNextDist");
  if (next) next.textContent = "—";
  const unit = document.getElementById("maneuverNextUnit");
  if (unit) unit.textContent = "";
  setManeuverIcon(document.getElementById("maneuverNextArrow"), null);
  const sr = document.getElementById("maneuverNextText");
  if (sr) sr.textContent = "";
}

function showManeuverHudShell() {
  const side = document.querySelector(".nav-hud-side");
  if (side) side.hidden = false;
}

function updateManeuverHud() {
  const route = state.route;
  const coords = route?.geometry?.coordinates;
  if (
    !state.navigationActive ||
    !route ||
    !coords?.length ||
    state.diverted
  ) {
    clearManeuverHud();
    return;
  }
  showManeuverHudShell();

  const idx = nearestShapeIndex(coords, state.lon, state.lat);
  const mans = route.maneuvers || [];
  const next = nextTurnManeuver(mans, idx) || route.next || mans[0];
  const distNext = nextTurnDistanceM() ?? 0;

  const parts = fmtMetersParts(distNext);
  document.getElementById("maneuverNextDist").textContent = parts.value;
  document.getElementById("maneuverNextUnit").textContent = parts.unit;
  setManeuverIcon(document.getElementById("maneuverNextArrow"), next);
  document.getElementById("maneuverNextText").textContent =
    `${maneuverVerb(next)} · ${fmtMeters(distNext)}`;

  const remain = pathMeters(coords, idx, coords.length - 1);
  document.getElementById("statRoute").textContent =
    remain >= 1000 ? (remain / 1000).toFixed(1) : (remain / 1000).toFixed(2);
}

function solarElevation(lat, lon, date = new Date()) {
  const rad = Math.PI / 180;
  const day = Math.floor(
    (Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()) -
      Date.UTC(date.getUTCFullYear(), 0, 0)) /
      86400000
  );
  const decl = 23.44 * Math.sin(rad * ((360 / 365) * (day - 81)));
  const utcH =
    date.getUTCHours() + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600;
  const lst = (utcH * 15 + lon + 360) % 360;
  const ha = lst - 180;
  const sinAlt =
    Math.sin(lat * rad) * Math.sin(decl * rad) +
    Math.cos(lat * rad) * Math.cos(decl * rad) * Math.cos(ha * rad);
  return Math.asin(Math.min(1, Math.max(-1, sinAlt))) / rad;
}

function currentThemeId() {
  return window.WardTheme?.read?.() || "classic";
}

function themePack() {
  const pack = window.WardTheme?.mapPack?.(currentThemeId()) || {
    ahead: "#00e5ff",
    done: "#2ad48a",
    mapDay: "liberty",
    mapNight: "dark",
  };
  const tile = (wh) => (wh === "dark" ? STYLE_NIGHT : STYLE_DAY);
  return {
    ahead: pack.ahead,
    done: pack.done,
    mapDay: tile(pack.mapDay),
    mapNight: tile(pack.mapNight),
  };
}

function mapStyleUrl(night) {
  const t = themePack();
  return night ? t.mapNight : t.mapDay;
}

function onSiteThemeChange() {
  applyRouteThemeColors();
  if (state.marker) {
    state.marker.remove();
    state.marker = null;
  }
  ensureMarker();
  applyDayNight(true);
}

function applyRouteThemeColors() {
  if (!state.map) return;
  const t = themePack();
  ensureRouteLayers();
  try {
    for (const [id, color] of [
      ["explore-route-glow", t.ahead],
      ["explore-route-line", t.ahead],
      ["explore-route-done-glow", t.done],
      ["explore-route-done-line", t.done],
    ]) {
      if (state.map.getLayer(id)) {
        state.map.setPaintProperty(id, "line-color", color);
      }
    }
  } catch {
    /* style not ready / layer missing */
  }
}

function applyDayNight(force = false) {
  const elev = solarElevation(state.lat, state.lon);
  const night = elev < -3;
  if (!state.map) {
    state.night = night;
    document.body.dataset.navNight = night ? "1" : "0";
    return;
  }
  if (!force && state.moving) {
    document.body.dataset.navNight = night ? "1" : "0";
    state.night = night;
    return;
  }
  const url = mapStyleUrl(night);
  const curStyle = state.map.getStyle()?.sprite || "";
  const sameNight = state.night === night && !force;
  // Skip reload if night flag unchanged and we're not forcing a theme swap
  if (sameNight && !force) {
    document.body.dataset.navNight = night ? "1" : "0";
    return;
  }
  state.night = night;
  document.body.dataset.navNight = night ? "1" : "0";
  const center = state.map.getCenter();
  const zoom = state.map.getZoom();
  const bearing = state.map.getBearing();
  const pitch = state.map.getPitch();
  // Avoid pointless setStyle when URL matches current tileset family
  void curStyle;
  state.map.setStyle(url);
  state.map.once("style.load", () => {
    state.map.jumpTo({ center, zoom, bearing, pitch });
    restoreRouteLayer();
    applyRouteThemeColors();
    // Liberty/dark ship their own building-3d — always sync visibility after style swap
    enableBuildings(!!state.buildingsOn);
    ensureMarker();
  });
}

function findBuildingSource(style) {
  const sources = style.sources || {};
  for (const [id, src] of Object.entries(sources)) {
    if (src.type === "vector") return id;
  }
  return null;
}

/** Toggle every fill-extrusion (style building-3d + our layer) for 2D perf. */
function setFillExtrusionVisibility(on) {
  if (!state.map) return;
  const style = state.map.getStyle();
  if (!style) return;
  let any = false;
  for (const layer of style.layers || []) {
    if (layer.type !== "fill-extrusion") continue;
    any = true;
    try {
      state.map.setLayoutProperty(
        layer.id,
        "visibility",
        on ? "visible" : "none"
      );
    } catch (_) {
      /* layer may be mid-reload */
    }
  }
  return any;
}

function enableBuildings(on) {
  if (!state.map || !state.webglOk) return;
  const style = state.map.getStyle();
  if (!style) return;
  const want = !!on;

  // Prefer toggling style-native extrusions (Liberty `building-3d`, etc.)
  const hadStyleExtrusions = setFillExtrusionVisibility(want);

  // Drop our fallback if the basemap already extrudes — avoid double draw
  if (hadStyleExtrusions && state.map.getLayer("wardrivrr-3d-buildings")) {
    try {
      state.map.removeLayer("wardrivrr-3d-buildings");
    } catch (_) {
      /* ignore */
    }
  }

  if (state.map.getLayer("wardrivrr-3d-buildings")) {
    if (!want) {
      try {
        state.map.removeLayer("wardrivrr-3d-buildings");
      } catch (_) {
        /* ignore */
      }
    }
    return;
  }
  if (!want) return;
  // Style already has 3D buildings — nothing more to add
  if (hadStyleExtrusions) return;

  const sourceId = findBuildingSource(style);
  if (!sourceId) {
    const toggle = document.getElementById("toggleBuildings");
    if (toggle) toggle.checked = false;
    state.buildingsOn = false;
    return;
  }
  const layers = style.layers || [];
  let beforeId;
  for (let i = layers.length - 1; i >= 0; i--) {
    if (layers[i].type === "symbol") {
      beforeId = layers[i].id;
      break;
    }
  }
  // Fallback extrusion when the basemap has none
  const layer = {
    id: "wardrivrr-3d-buildings",
    source: sourceId,
    "source-layer": "building",
    type: "fill-extrusion",
    minzoom: 16,
    paint: {
      "fill-extrusion-color": state.night ? "#1c222b" : "#c8ced6",
      "fill-extrusion-height": [
        "coalesce",
        ["get", "render_height"],
        ["get", "height"],
        10,
      ],
      "fill-extrusion-base": 0,
      "fill-extrusion-opacity": 0.55,
    },
  };
  try {
    if (beforeId) state.map.addLayer(layer, beforeId);
    else state.map.addLayer(layer);
  } catch (err) {
    console.warn("3D buildings failed", err);
    state.buildingsOn = false;
  }
}

function emptyLine() {
  return { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [] } };
}

function routeWidthExpr(base) {
  // base ≈ mid-zoom width; scales up with zoom for drive readability
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    12,
    base * 0.65,
    16,
    base,
    18,
    base * 1.4,
  ];
}

function ensureRouteLayers() {
  if (!state.map) return;
  // MapLibre throws (and used to recurse via applyRouteThemeColors) if we touch
  // sources before the style is ready or when layers already exist.
  if (typeof state.map.isStyleLoaded === "function" && !state.map.isStyleLoaded()) {
    return;
  }
  if (state.map.getSource("explore-route-ahead")) return;
  const t = themePack();
  try {
    state.map.addSource("explore-route-ahead", { type: "geojson", data: emptyLine() });
    state.map.addSource("explore-route-done", { type: "geojson", data: emptyLine() });
    state.map.addLayer({
      id: "explore-route-glow",
      type: "line",
      source: "explore-route-ahead",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": t.ahead,
        "line-width": routeWidthExpr(22),
        "line-opacity": 0.28,
      },
    });
    state.map.addLayer({
      id: "explore-route-line",
      type: "line",
      source: "explore-route-ahead",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": t.ahead,
        "line-width": routeWidthExpr(14),
        "line-opacity": 0.98,
      },
    });
    state.map.addLayer({
      id: "explore-route-done-glow",
      type: "line",
      source: "explore-route-done",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": t.done,
        "line-width": routeWidthExpr(24),
        "line-opacity": 0.32,
      },
    });
    state.map.addLayer({
      id: "explore-route-done-line",
      type: "line",
      source: "explore-route-done",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": t.done,
        "line-width": routeWidthExpr(15),
        "line-opacity": 0.98,
      },
    });
  } catch (err) {
    console.warn("route layers not ready", err);
  }
}

function restoreRouteLayer() {
  if (!state.route?.geometry?.coordinates?.length || !state.map) return;
  ensureRouteLayers();
  updateRouteProgress();
}

function updateRouteProgress() {
  const coords = state.route?.geometry?.coordinates;
  if (!coords?.length || !state.map) return;
  ensureRouteLayers();
  const idx = nearestShapeIndex(coords, state.lon, state.lat);
  const doneCoords = coords.slice(0, Math.max(2, idx + 1));
  const aheadCoords = coords.slice(Math.max(0, idx));
  if (aheadCoords.length < 2) {
    // Finished — paint all green
    state.map.getSource("explore-route-done").setData({
      type: "Feature",
      properties: {},
      geometry: { type: "LineString", coordinates: coords },
    });
    state.map.getSource("explore-route-ahead").setData(emptyLine());
    return;
  }
  state.map.getSource("explore-route-done").setData({
    type: "Feature",
    properties: {},
    geometry: { type: "LineString", coordinates: doneCoords },
  });
  state.map.getSource("explore-route-ahead").setData({
    type: "Feature",
    properties: {},
    geometry: { type: "LineString", coordinates: aheadCoords },
  });
}

function setRoute(route) {
  state.route = route;
  state.diverted = false;
  state.wrongWayStreak = 0;
  state.offRouteStreak = 0;
  state.lastGoodLat = state.lat;
  state.lastGoodLon = state.lon;
  const geom = route?.geometry;
  if (!geom?.coordinates?.length) {
    clearManeuverHud();
    return;
  }
  state.routeGeo = { type: "Feature", properties: {}, geometry: geom };
  restoreRouteLayer();
  applyRouteThemeColors();
  showManeuverHudShell();
  updateManeuverHud();
}

function bearingDeg(lat1, lon1, lat2, lon2) {
  const toR = Math.PI / 180;
  const φ1 = lat1 * toR;
  const φ2 = lat2 * toR;
  const Δλ = (lon2 - lon1) * toR;
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x =
    Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function angleDiffAbs(a, b) {
  return Math.abs(((a - b + 540) % 360) - 180);
}

/** Bearing of the route looking ~40 m ahead from the nearest shape point. */
function routeAheadBearing(coords, lon, lat) {
  if (!coords?.length || coords.length < 2) return null;
  const i = nearestShapeIndex(coords, lon, lat);
  let j = i;
  let acc = 0;
  while (j < coords.length - 1 && acc < 40) {
    acc += haversineM(
      coords[j][1],
      coords[j][0],
      coords[j + 1][1],
      coords[j + 1][0]
    );
    j += 1;
  }
  if (j <= i) j = Math.min(i + 2, coords.length - 1);
  if (j === i) return null;
  return bearingDeg(coords[i][1], coords[i][0], coords[j][1], coords[j][0]);
}

function triggerReplan(now, reason) {
  if (!state.navigationActive) return;
  clearManeuverHud();
  document.getElementById("navHint").textContent = reason;
  if (state.exploreInFlight) return;
  if (now - state.lastReplanAt < REPLAN_COOLDOWN_MS) return;
  state.lastReplanAt = now;
  startExplore({ auto: true, reason });
}

function markLastGood() {
  state.lastGoodLat = state.lat;
  state.lastGoodLon = state.lon;
}

function distFromLastGoodM() {
  if (state.lastGoodLat == null || state.lastGoodLon == null) return 0;
  return haversineM(
    state.lastGoodLat,
    state.lastGoodLon,
    state.lat,
    state.lon
  );
}

function routeIssue(coords) {
  const d = distToRouteM(state.lon, state.lat, coords);
  if (d > OFF_ROUTE_M) return "off-route";
  // Parked: do not treat gpsd track as wrong-way
  if ((state.speedKmh || 0) < WRONG_WAY_MIN_SPEED_KMH) return null;
  const ahead = routeAheadBearing(coords, state.lon, state.lat);
  if (ahead == null) return null;
  return angleDiffAbs(state.heading, ahead) < WRONG_WAY_DEG
    ? null
    : "wrong-way";
}

/**
 * Leave corridor / wrong way → hide TBT, keep the route.
 * Requires WRONG_WAY_STREAK_N consecutive bad fixes (gpsd lag hysteresis).
 * Full replan only after >80 m from the last correct point.
 */
function checkOffRoute(now) {
  if (!state.navigationActive) return;
  const coords = state.route?.geometry?.coordinates;
  if (!coords?.length) return;

  const issue = routeIssue(coords);
  if (!issue) {
    state.wrongWayStreak = 0;
    state.offRouteStreak = 0;
    markLastGood();
    if (state.diverted) {
      state.diverted = false;
      setNavHint("Joined route again");
      showManeuverHudShell();
      updateManeuverHud();
      updateRouteProgress();
    }
    return;
  }

  let streak;
  if (issue === "off-route") {
    state.offRouteStreak = (state.offRouteStreak || 0) + 1;
    state.wrongWayStreak = 0;
    streak = state.offRouteStreak;
  } else {
    state.wrongWayStreak = (state.wrongWayStreak || 0) + 1;
    state.offRouteStreak = 0;
    streak = state.wrongWayStreak;
  }
  if (streak < WRONG_WAY_STREAK_N) {
    return; // transient GPS / heading noise
  }

  state.diverted = true;
  clearManeuverHud();

  const away = distFromLastGoodM();
  if (away < REROUTE_FROM_LAST_GOOD_M) {
    setNavHint(
      `Off route · ${Math.round(away)}/${REROUTE_FROM_LAST_GOOD_M} m to replan`
    );
    return;
  }

  triggerReplan(now, "Far from route — recalculating…");
}

function setNavHint(text) {
  const el = document.getElementById("navHint");
  if (!el) return;
  el.textContent = text || "";
  if (DEBUG_NAV) el.hidden = false;
}

function ensureToastHost() {
  let host = document.getElementById("achToastHost");
  if (!host) {
    host = document.createElement("div");
    host.id = "achToastHost";
    host.className = "nav-ach-toasts";
    document.querySelector(".nav-main")?.appendChild(host);
  }
  return host;
}

function playAchievementSound() {
  if (!state.achievementSounds) return;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) return;
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const now = ctx.currentTime;
    const notes = [523.25, 659.25, 783.99];
    notes.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.value = freq;
      osc.connect(gain);
      gain.connect(ctx.destination);
      const t0 = now + i * 0.09;
      gain.gain.setValueAtTime(0.001, t0);
      gain.gain.exponentialRampToValueAtTime(0.07, t0 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, t0 + 0.22);
      osc.start(t0);
      osc.stop(t0 + 0.24);
    });
    setTimeout(() => ctx.close().catch(() => {}), 800);
  } catch {
    /* ignore */
  }
}

function showAchievementToasts(list) {
  if (!list?.length) return;
  const host = ensureToastHost();
  playAchievementSound();
  for (const a of list) {
    const el = document.createElement("div");
    el.className = "nav-ach-toast";
    const xp = Number(a.xp) || 0;
    const xpBit = xp ? `<em class="nav-ach-xp">+${xp} XP</em>` : "";
    el.innerHTML = `<strong>${a.title || "Achievement"}</strong>${xpBit}<span>${a.flavour || a.description || ""}</span>`;
    host.appendChild(el);
    setTimeout(() => el.classList.add("is-on"), 20);
    setTimeout(() => {
      el.classList.remove("is-on");
      setTimeout(() => el.remove(), 400);
    }, 5200);
  }
}

function playAnomalySound(kind) {
  if (!state.achievementSounds) return;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) return;
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    if (kind === "space") {
      osc.type = "sine";
      osc.frequency.setValueAtTime(520, now);
      osc.frequency.exponentialRampToValueAtTime(220, now + 0.28);
      gain.gain.setValueAtTime(0.08, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.32);
      osc.start(now);
      osc.stop(now + 0.34);
    } else if (kind === "train") {
      osc.type = "triangle";
      osc.frequency.setValueAtTime(180, now);
      osc.frequency.setValueAtTime(240, now + 0.08);
      osc.frequency.setValueAtTime(180, now + 0.16);
      gain.gain.setValueAtTime(0.07, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.22);
      osc.start(now);
      osc.stop(now + 0.24);
    } else {
      osc.type = "square";
      osc.frequency.setValueAtTime(880, now);
      gain.gain.setValueAtTime(0.05, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.12);
      osc.start(now);
      osc.stop(now + 0.14);
    }
    setTimeout(() => ctx.close().catch(() => {}), 500);
  } catch {
    /* ignore audio failures */
  }
}

function showAnomalyToasts(list) {
  if (!state.anomalyAlerts || !list?.length) return;
  const now = Date.now();
  if (now - state.anomalyLastToastAt < ANOMALY_COOLDOWN_MS) return;
  const host = ensureToastHost();
  for (const a of list) {
    const nid = String(a.network_id || "").toLowerCase();
    const key = `${a.id || "x"}:${nid}`;
    if (state.anomalyAlerted.has(key)) continue;
    state.anomalyAlerted.add(key);
    state.anomalyLastToastAt = now;
    const el = document.createElement("div");
    el.className = "nav-ach-toast nav-anomaly-toast";
    const nameBit = a.name ? `<code>${a.name}</code>` : "";
    el.innerHTML = `<strong>${a.toast || a.title || "Special find"}</strong><span>${a.flavour || ""}${nameBit ? ` · ${nameBit}` : ""}</span>`;
    host.appendChild(el);
    setTimeout(() => el.classList.add("is-on"), 20);
    setTimeout(() => {
      el.classList.remove("is-on");
      setTimeout(() => el.remove(), 400);
    }, 4800);
    playAnomalySound(a.sound || "blip");
    break; // one toast per cooldown window
  }
}

async function setAnomalyAlerts(enabled) {
  state.anomalyAlerts = !!enabled;
  const toggle = document.getElementById("toggleAnomaly");
  if (toggle) toggle.checked = state.anomalyAlerts;
  try {
    await WardAuth.apiFetch("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ anomaly_alerts: state.anomalyAlerts }),
    });
  } catch {
    /* ignore */
  }
}

function makeMarkerEl() {
  const el = document.createElement("div");
  const theme = currentThemeId();
  const pack = themePack();
  el.className = `nav-map-marker theme-${theme}`;
  el.style.setProperty("--nav-marker-fill", pack.ahead || "#00e5ff");
  // Classic turn-by-turn chevron (points “up” = map north; Marker rotates by heading)
  el.innerHTML = `
    <div class="nav-marker-chevron" aria-hidden="true">
      <svg viewBox="0 0 48 56" width="40" height="46">
        <path
          class="nav-chevron-shadow"
          d="M24 4 L44 42 L24 34 L4 42 Z"
        />
        <path
          class="nav-chevron-fill"
          d="M24 6 L42 40 L24 32 L6 40 Z"
        />
        <path
          class="nav-chevron-edge"
          d="M24 6 L42 40 L24 32 L6 40 Z"
          fill="none"
        />
      </svg>
    </div>`;
  return el;
}

function ensureMarker() {
  if (!state.map || !state.spawned) return;
  const lat = state.dispLat != null ? state.dispLat : state.lat;
  const lon = state.dispLon != null ? state.dispLon : state.lon;
  const heading = state.dispHeading != null ? state.dispHeading : state.heading;
  if (!state.marker) {
    state.marker = new maplibregl.Marker({
      element: makeMarkerEl(),
      rotationAlignment: "map",
      pitchAlignment: "map",
      anchor: "center",
    })
      .setLngLat([lon, lat])
      .setRotation(heading)
      .addTo(state.map);
  } else {
    state.marker.setLngLat([lon, lat]);
    state.marker.setRotation(heading);
  }
}

/** Lerp chevron pose every frame so motion stays smooth between GPS polls. */
function updateDisplayPose(now) {
  if (!state.spawned) return;
  if (state.dispLat == null || state.dispLon == null) {
    state.dispLat = state.lat;
    state.dispLon = state.lon;
    state.dispHeading = state.heading;
    state.lastDispAt = now;
    return;
  }
  const prev = state.lastDispAt || now;
  const dt = Math.min(0.05, Math.max(0.001, (now - prev) / 1000));
  state.lastDispAt = now;
  const aPos = 1 - Math.exp(-CAM_SMOOTH * dt);
  const aBrg = 1 - Math.exp(-BEARING_SMOOTH * dt);
  state.dispLat += (state.lat - state.dispLat) * aPos;
  state.dispLon += (state.lon - state.dispLon) * aPos;
  state.dispHeading = lerpAngleDeg(state.dispHeading, state.heading, aBrg);
}

/** Pause GPS camera follow after a user pan/rotate (same cooldown for both). */
function noteUserCameraGesture() {
  if (state.camProgrammatic) return;
  state.userCamUntil = performance.now() + USER_CAM_COOLDOWN_MS;
  state.userCamActive = true;
  state.userCamGesturePending = false;
}

function withProgrammaticCam(fn) {
  state.camProgrammatic = true;
  try {
    fn();
  } finally {
    // Clear after MapLibre has dispatched any synthetic pitch/move events
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        state.camProgrammatic = false;
      });
    });
  }
}

function bindMapCameraGestures() {
  if (!state.map || state.map._wardCamGestures) return;
  state.map._wardCamGestures = true;
  // ONLY real pointer/touch/wheel. jumpTo fires synthetic rotate/drag without
  // originalEvent — treating those as user input caused 3s freeze steps.
  const bumpUser = (e) => {
    if (state.camProgrammatic) return;
    if (e?.originalEvent) noteUserCameraGesture();
  };
  // Pause follow immediately on press — otherwise jumpTo fights the pan before dragstart
  const bumpPress = (e) => {
    if (state.camProgrammatic || state.spawnMode) return;
    if (e?.originalEvent) noteUserCameraGesture();
  };
  state.map.on("mousedown", bumpPress);
  state.map.on("touchstart", bumpPress);
  state.map.on("dragstart", bumpUser);
  state.map.on("rotatestart", bumpUser);
  state.map.on("pitchstart", bumpUser);
  state.map.on("zoomstart", bumpUser);
}

function currentPitch() {
  return state.view3d ? PITCH_3D : PITCH_2D;
}

function loadNavPrefs() {
  const dead = localStorage.getItem(DEAD_ENDS_KEY);
  state.excludeDeadEnds = dead === "1";
  const v3 = localStorage.getItem(VIEW_3D_KEY);
  if (v3 === "0" || v3 === "1") {
    state.view3d = v3 === "1";
  } else {
    // Migrate old buildings-only pref
    const b = localStorage.getItem(BUILDINGS_KEY);
    state.view3d = b !== "0";
  }
  state.buildingsOn = state.view3d && state.webglOk;
  state.camPitch = currentPitch();
  const deadToggle = document.getElementById("toggleDeadEnds");
  if (deadToggle) deadToggle.checked = state.excludeDeadEnds;
  const promptDead = document.getElementById("levelPromptDeadEnds");
  if (promptDead) promptDead.checked = state.excludeDeadEnds;
}

function setExcludeDeadEnds(on, { persist = true } = {}) {
  state.excludeDeadEnds = !!on;
  if (persist) {
    localStorage.setItem(DEAD_ENDS_KEY, state.excludeDeadEnds ? "1" : "0");
  }
  const deadToggle = document.getElementById("toggleDeadEnds");
  if (deadToggle) deadToggle.checked = state.excludeDeadEnds;
  const promptDead = document.getElementById("levelPromptDeadEnds");
  if (promptDead) promptDead.checked = state.excludeDeadEnds;
}

function lerpAngleDeg(a, b, t) {
  const d = ((Number(b) - Number(a) + 540) % 360) - 180;
  return (Number(a) + d * t + 360) % 360;
}

function angleDiffAbsDeg(a, b) {
  return Math.abs(((Number(a) - Number(b) + 540) % 360) - 180);
}

/**
 * Accel until half the original gap is closed, then decelerate.
 * `along` = 0 at start → 1 at target (based on remaining / origin distance).
 */
function catchUpGain(along, kStart, kPeak, kEnd) {
  const a = Math.min(1, Math.max(0, along));
  if (a < 0.5) {
    // Ease-in toward peak (t: 0 → 1 over first half)
    const t = a / 0.5;
    const ease = t * t;
    return kStart + (kPeak - kStart) * ease;
  }
  // Ease-out from peak toward end (t: 0 → 1 over second half)
  const t = (a - 0.5) / 0.5;
  const ease = t * (2 - t); // smooth decelerate blend
  return kPeak + (kEnd - kPeak) * ease;
}

function beginCamCatchUp(distM, brgErr) {
  state.camCatchingUp = true;
  state.catchOriginDistM = Math.max(distM, 1);
  state.catchOriginBrgErr = Math.max(brgErr, 1);
}

function syncNavToggleUi() {
  const btn = document.getElementById("btnNavToggle");
  if (!btn) return;
  const on = !!state.navigationActive;
  // Colorful when routing on; grayed when off
  btn.classList.toggle("is-on", on);
  btn.classList.toggle("is-muted-look", !on);
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  btn.title = on ? "Stop navigation" : "Start navigation";
  btn.setAttribute("aria-label", on ? "Stop navigation" : "Start navigation");
}

function clearRouteLayers() {
  if (!state.map) return;
  try {
    const ahead = state.map.getSource("explore-route-ahead");
    const done = state.map.getSource("explore-route-done");
    if (ahead) ahead.setData(emptyLine());
    if (done) done.setData(emptyLine());
  } catch (_) {
    /* ignore */
  }
}

function stopNavigation({ silent = false } = {}) {
  state.navigationActive = false;
  state.route = null;
  state.routeGeo = null;
  state.diverted = false;
  state.autoExploreStarted = false;
  state.autoExploreAttempts = 0;
  state.autoExploreRetryAt = 0;
  state.lastGoodLat = null;
  state.lastGoodLon = null;
  clearManeuverHud();
  clearRouteLayers();
  syncNavToggleUi();
  const replanBtn = document.getElementById("btnReplan");
  if (replanBtn) replanBtn.disabled = true;
  if (!silent) setNavHint("Navigation stopped — map follow still on.");
}

async function startNavigation() {
  if (!state.spawned) {
    setNavHint("Waiting for GPS spawn…");
    return false;
  }
  state.navigationActive = true;
  syncNavToggleUi();
  if (!state.levelId) {
    setNavHint("No level here — looking up a place…");
    await promptIfUnknownOnSpawn();
    return true;
  }
  const ok = await startExplore({ auto: false, reason: "Navigation started" });
  if (ok) state.autoExploreStarted = true;
  return ok;
}

function toggleNavigation() {
  if (state.navigationActive) stopNavigation();
  else startNavigation();
}

/** Smooth chase camera — lerp position + shortest-arc bearing toward GPS/sim pose. */
function followCamera(now) {
  if (!state.map || !state.spawned) return;
  updateDisplayPose(now);
  ensureMarker();

  // User is exploring the map — keep GPS marker moving, leave camera alone
  if (state.userCamUntil && now < state.userCamUntil) {
    state.lastCam = now;
    return;
  }
  if (state.userCamActive) {
    // Cooldown just ended — start from the panned view, then ease back
    const c = state.map.getCenter();
    state.camLat = c.lat;
    state.camLon = c.lng;
    state.camBearing = state.map.getBearing();
    state.camPitch = state.map.getPitch();
    state.camZoom = state.map.getZoom();
    state.userCamActive = false;
    const d0 = haversineM(state.camLat, state.camLon, state.dispLat, state.dispLon);
    const b0 = angleDiffAbsDeg(state.camBearing, state.dispHeading);
    beginCamCatchUp(d0, b0);
  }

  if (state.camLat == null || state.camLon == null) {
    state.camLat = state.dispLat;
    state.camLon = state.dispLon;
    state.camBearing = state.dispHeading;
    state.camPitch = currentPitch();
    state.camZoom = targetZoom();
    state.camCatchingUp = false;
  }
  const prev = state.lastCam || now;
  const dt = Math.min(0.05, Math.max(0.001, (now - prev) / 1000));
  state.lastCam = now;

  const targetLat = state.dispLat;
  const targetLon = state.dispLon;
  const targetBrg = state.dispHeading;
  const distM = haversineM(state.camLat, state.camLon, targetLat, targetLon);
  const brgErr = angleDiffAbsDeg(state.camBearing, targetBrg);

  if (!state.camCatchingUp && distM > CATCH_RESUME_M) {
    beginCamCatchUp(distM, brgErr);
  }
  // Target drifted farther than when we started — reset the accel profile
  if (state.camCatchingUp && distM > state.catchOriginDistM * 1.05) {
    state.catchOriginDistM = distM;
    state.catchOriginBrgErr = Math.max(brgErr, state.catchOriginBrgErr);
  }

  // Pitch is binary 2D/3D — snap, never ease over seconds
  state.camPitch = currentPitch();
  const wantZoom = targetZoom();
  if (state.camZoom == null || !Number.isFinite(state.camZoom)) {
    state.camZoom = wantZoom;
  }

  if (state.camCatchingUp) {
    const alongPos =
      1 - Math.min(1, distM / Math.max(state.catchOriginDistM, 1e-3));
    const posK = catchUpGain(
      alongPos,
      CATCH_K_START,
      CATCH_K_PEAK,
      CATCH_K_END
    );
    const aPos = 1 - Math.exp(-posK * dt);
    // Phase 1: only slide XY back toward the marker
    state.camLat += (targetLat - state.camLat) * aPos;
    state.camLon += (targetLon - state.camLon) * aPos;

    // Phase 2: once close, ease bearing + zoom (pan keeps refining)
    if (distM <= CATCH_ALIGN_M) {
      const alongBrg =
        1 - Math.min(1, brgErr / Math.max(state.catchOriginBrgErr, 1e-3));
      const brgK = catchUpGain(
        alongBrg,
        CATCH_K_START,
        CATCH_K_PEAK,
        CATCH_K_END
      );
      const aBrg = 1 - Math.exp(-brgK * dt);
      const aZoom = 1 - Math.exp(-ZOOM_SMOOTH * dt);
      state.camBearing = lerpAngleDeg(state.camBearing, targetBrg, aBrg);
      state.camZoom += (wantZoom - state.camZoom) * aZoom;
    }
    // else: hold user bearing/zoom until marker is close

    if (distM <= CATCH_LOCK_M && brgErr <= CATCH_LOCK_DEG) {
      state.camCatchingUp = false;
    }
  } else {
    state.camLat = targetLat;
    state.camLon = targetLon;
    state.camBearing = targetBrg;
    const aZoom = 1 - Math.exp(-ZOOM_SMOOTH * dt);
    state.camZoom += (wantZoom - state.camZoom) * aZoom;
  }

  // Guard so synthetic rotate/move from jumpTo never re-arms the 3s cooldown
  state.camProgrammatic = true;
  try {
    state.map.jumpTo({
      center: [state.camLon, state.camLat],
      bearing: state.camBearing,
      pitch: state.camPitch,
      zoom: state.camZoom,
    });
  } finally {
    state.camProgrammatic = false;
  }
}

function fmtUnlockKm(meters) {
  const km = Math.max(0, Number(meters) || 0) / 1000;
  if (km < 10) return km.toFixed(2);
  if (km < 100) return km.toFixed(1);
  return String(Math.round(km));
}

function updateUnlockHud() {
  const el = document.getElementById("statUnlock");
  if (el) el.textContent = fmtUnlockKm(state.sessionUnlockM);
}

function setRadioCell(prefix, pack) {
  const seen = document.getElementById(`stat${prefix}Seen`);
  const neu = document.getElementById(`stat${prefix}New`);
  if (!seen || !neu) return;
  const s = Number(pack?.seen) || 0;
  const n = Number(pack?.new) || 0;
  seen.textContent = String(s);
  neu.textContent = String(n);
}

function updateRadioHud(radio) {
  if (!radio) return;
  setRadioCell("Wifi", radio.wifi);
  setRadioCell("Bt", radio.bt);
  setRadioCell("Ble", radio.ble);
}

async function pushFix(unlock = true) {
  if (state.pushInFlight || state.followLiveGps) return;
  state.pushInFlight = true;
  try {
    const res = await WardAuth.apiFetch("/api/gps/fix", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lat: state.lat,
        lon: state.lon,
        heading_deg: state.heading,
        speed_mps: state.speedKmh / 3.6,
        accuracy_m: 8,
        source: "sim",
        level_id: state.levelId,
        unlock,
        session_started_at: state.sessionStartedAt,
      }),
    });
    const data = await res.json().catch(() => ({}));
    // Server returns road-snapped lat/lon — drive icon + local state follow that
    const f = data.fix;
    if (f?.lat != null && f?.lon != null) {
      applyDisplayPosition(Number(f.lon), Number(f.lat));
      ensureMarker();
    }
    if (data.unlock?.newly_explored) {
      state.sessionUnlockM += Number(data.unlock.newly_explored) * 20;
      updateUnlockHud();
    }
    if (data.radio) updateRadioHud(data.radio);
    if (data.anomalies?.length) {
      showAnomalyToasts(data.anomalies);
    }
    if (data.newly_unlocked?.length) {
      showAchievementToasts(data.newly_unlocked);
    }
  } finally {
    state.pushInFlight = false;
  }
}

function setFollowLiveGps(on) {
  state.followLiveGps = !!on;
  const btn = document.getElementById("btnFollowGps");
  if (btn) {
    btn.classList.toggle("btn-primary", state.followLiveGps);
    btn.textContent = state.followLiveGps ? "Following live GPS…" : "Follow live GPS";
  }
  if (state.followLiveGps) {
    state.spawned = true;
    state.spawnMode = false;
    if (!state.sessionStartedAt) {
      state.sessionStartedAt = new Date().toISOString();
    }
    const spawnBtn = document.getElementById("btnSpawn");
    if (spawnBtn) spawnBtn.textContent = "Respawn";
    const startBtn = document.getElementById("btnStart");
    if (startBtn) startBtn.disabled = !state.levelId;
    setNavHint(
      state.gpsSource === "gpsd"
        ? "Following gpsd"
        : "Following live GPS"
    );
    const mapEl = document.getElementById("navMap");
    if (mapEl) mapEl.style.cursor = "";
    ensureMarker();
    setDriveHot(true);
    wakeSimLoop();
  } else if (DEBUG_NAV) {
    setNavHint("Follow live GPS off — WASD sim again.");
  }
}

async function maybeAutoExplore() {
  if (!state.navigationActive) return;
  if (state.autoExploreStarted || !state.spawned || !state.levelId) return;
  if (!state.followLiveGps) return;
  if (state.exploreInFlight || state.route) return;
  if (Date.now() < state.autoExploreRetryAt) return;
  let started = false;
  try {
    started = await startExplore({ auto: true, reason: "Auto explore" });
  } catch (err) {
    console.warn("Auto explore failed", err);
  }
  if (started) {
    state.autoExploreStarted = true;
    state.autoExploreAttempts = 0;
    state.autoExploreRetryAt = 0;
    return;
  }
  state.autoExploreAttempts += 1;
  const delay = Math.min(
    AUTO_EXPLORE_RETRY_MAX_MS,
    AUTO_EXPLORE_RETRY_BASE_MS * 2 ** Math.min(4, state.autoExploreAttempts - 1)
  );
  state.autoExploreRetryAt = Date.now() + delay;
}

async function pollFollowGps(now) {
  if (!state.followLiveGps || state.followInFlight) return;
  if (now - state.lastFollowAt < FOLLOW_MS) return;
  state.lastFollowAt = now;
  state.followInFlight = true;
  try {
    const q = state.sessionStartedAt
      ? `?session_started_at=${encodeURIComponent(state.sessionStartedAt)}`
      : "";
    const res = await WardAuth.apiFetch(`/api/gps/fix${q}`);
    const data = await res.json().catch(() => ({}));
    const fix = data.fix;
    if (!fix || fix.lat == null || fix.lon == null) {
      setNavHint("Waiting for GPS…");
      return;
    }
    state.gpsSource = fix.source || state.gpsSource;
    if (fix.session_started_at) {
      state.sessionStartedAt = fix.session_started_at;
    }
    // Server lat/lon are road-snapped (unlock uses same). Route polish for HUD.
    const prevLat = state.lat;
    const prevLon = state.lon;
    applyDisplayPosition(Number(fix.lon), Number(fix.lat));
    if (fix.heading_deg != null) state.heading = Number(fix.heading_deg);
    if (fix.speed_mps != null) state.speedKmh = Number(fix.speed_mps) * 3.6;
    const moved =
      Math.abs(state.lat - prevLat) > 1e-7 || Math.abs(state.lon - prevLon) > 1e-7;
    state.moving = (state.speedKmh || 0) > 0.3 || moved;
    if (state.moving) setDriveHot(true);
    ensureMarker();
    // Camera smoothed in simFrame; only update pose targets here
    if (data.radio) updateRadioHud(data.radio);
    if (data.anomalies?.length) showAnomalyToasts(data.anomalies);
    if (data.newly_unlocked?.length) showAchievementToasts(data.newly_unlocked);
    const spd = document.getElementById("statSpeed");
    if (spd && Math.round(state.speedKmh) !== state.lastSpeedUi) {
      state.lastSpeedUi = Math.round(state.speedKmh);
      spd.textContent = String(state.lastSpeedUi);
    }
    if (DEBUG_NAV) {
      const sn = fix.snap || {};
      const snapBit = fix.snapped || sn.snapped
        ? `snap ${Number(sn.distance_m || fix.snap_dist_m || 0).toFixed(0)}m`
        : sn.held
          ? "snap held"
          : sn.degraded
            ? "raw/degraded"
            : "—";
      setNavHint(
        `${fix.source || "gps"} · ${snapBit} · ${Math.round(state.speedKmh)} km/h`
      );
    }
    maybeAutoExplore();
  } finally {
    state.followInFlight = false;
  }
}

/** Auto-enable follow when backend has gpsd/client fix (car mode). */
async function tryAutoFollowFromGpsd() {
  try {
    const res = await WardAuth.apiFetch("/api/gps/fix");
    const data = await res.json().catch(() => ({}));
    const fix = data.fix;
    if (!fix || fix.lat == null) return false;
    if (fix.source === "gpsd" || fix.source === "client") {
      state.gpsSource = fix.source;
      setFollowLiveGps(true);
      return true;
    }
  } catch {
    /* ignore */
  }
  return false;
}

function closeLevelPrompt(dismiss = false) {
  const el = document.getElementById("levelPrompt");
  el.hidden = true;
  state.promptOpen = false;
  document.querySelector(".nav-main")?.classList.remove("is-prompting");
  if (state.promptTimer) {
    cancelAnimationFrame(state.promptTimer);
    state.promptTimer = null;
  }
  if (dismiss && state.promptSuggestion) {
    state.dismissedLabel = state.promptSuggestion.label || state.dismissedLabel;
  }
  state.promptSuggestion = null;
  document.getElementById("levelPromptFill").style.width = "0%";
}

function tickYesFill(now) {
  if (!state.promptOpen) return;
  const t = Math.min(1, (now - state.promptFillStart) / YES_FILL_MS);
  document.getElementById("levelPromptFill").style.width = `${t * 100}%`;
  document.getElementById("levelPromptSec").textContent = Math.ceil(
    (YES_FILL_MS * (1 - t)) / 1000
  );
  if (t >= 1) {
    acceptLevelPrompt();
    return;
  }
  state.promptTimer = requestAnimationFrame(tickYesFill);
}

function fmtBuildEta(sec) {
  if (sec == null || !Number.isFinite(sec)) return "estimating…";
  if (sec <= 0) return "almost done";
  if (sec < 60) return `~${Math.ceil(sec)}s left`;
  const m = Math.floor(sec / 60);
  const s = Math.ceil(sec % 60);
  return `~${m}m ${s}s left`;
}

function setBuildStage(stage) {
  const order = ["extract", "roads", "finish"];
  const mapped =
    stage === "download" ? "extract" : stage === "done" ? "finish" : stage;
  const idx = order.indexOf(mapped);
  document.querySelectorAll("#navBuildStages li").forEach((li) => {
    const si = order.indexOf(li.dataset.stage);
    li.classList.toggle("active", si === idx);
    li.classList.toggle("done", idx >= 0 && si < idx);
  });
}

function showBuildOverlay(title) {
  state.building = true;
  document.querySelector(".nav-main")?.classList.add("is-building");
  const el = document.getElementById("navBuildOverlay");
  el.hidden = false;
  document.getElementById("navBuildTitle").textContent =
    title || `Building ${state.levelName}…`;
  document.getElementById("navBuildMessage").textContent = "Starting…";
  document.getElementById("navBuildFill").style.width = "2%";
  document.getElementById("navBuildPct").textContent = "0%";
  document.getElementById("navBuildEta").textContent = "estimating…";
  setBuildStage("extract");
}

function updateBuildOverlay(job) {
  const result = job.result || {};
  const progress = Math.max(0, Math.min(1, Number(job.progress) || 0));
  const pct = Math.round(progress * 100);
  document.getElementById("navBuildFill").style.width = `${pct}%`;
  document.getElementById("navBuildPct").textContent = `${pct}%`;
  document.getElementById("navBuildMessage").textContent =
    result.message ||
    (job.status === "queued" ? "Waiting in queue…" : "Working…");
  document.getElementById("navBuildEta").textContent = fmtBuildEta(
    result.eta_seconds
  );
  if (result.stage) setBuildStage(result.stage);
  document.getElementById("navHint").textContent =
    `${state.levelName}: ${pct}% · ${result.message || job.status || "building"}`;
}

function hideBuildOverlay() {
  state.building = false;
  document.querySelector(".nav-main")?.classList.remove("is-building");
  document.getElementById("navBuildOverlay").hidden = true;
}

function setLevelPromptCopy(kind) {
  const title = document.querySelector("#levelPrompt .nav-level-title");
  const sub = document.querySelector("#levelPrompt .nav-level-sub");
  if (!title || !sub) return;
  if (kind === "create") {
    title.textContent = "Generate level?";
    sub.innerHTML =
      "No level covers this spot yet. Auto-confirm in " +
      '<span id="levelPromptSec">20</span>s';
  } else {
    title.textContent = "Load level?";
    sub.innerHTML =
      "You’re outside the current level. Auto-confirm in " +
      '<span id="levelPromptSec">20</span>s';
  }
}

/** @returns {boolean} true if the Yes-timer prompt was shown */
function openLevelPrompt(payload, kind = "switch") {
  if (!state.navigationActive) return false;
  if (state.promptOpen || state.building) return false;
  const label = payload.label || payload.suggestion?.name;
  if (!label || label === state.dismissedLabel) return false;

  if (payload.already_have && payload.level?.id) {
    if (Number(payload.level.id) === Number(state.levelId)) {
      // Still resolving to the level we just left — keep waiting for a new place
      return false;
    }
    state.promptSuggestion = {
      label,
      existingId: payload.level.id,
      existingStatus: payload.level.status,
    };
    setLevelPromptCopy("switch");
  } else if (payload.suggestion) {
    state.promptSuggestion = { label, create: payload.suggestion };
    setLevelPromptCopy(kind === "create" || !state.levelId ? "create" : "switch");
  } else {
    return false;
  }
  state.promptOpen = true;
  // Prefill dead-end option from last choice; user can change before auto-confirm
  const promptDead = document.getElementById("levelPromptDeadEnds");
  if (promptDead) promptDead.checked = !!state.excludeDeadEnds;
  document.getElementById("levelPromptName").textContent = label;
  document.getElementById("levelPrompt").hidden = false;
  document.querySelector(".nav-main")?.classList.add("is-prompting");
  state.promptFillStart = performance.now();
  state.promptTimer = requestAnimationFrame(tickYesFill);
  return true;
}

async function resumeExploreAfterLevel() {
  if (!state.navigationActive || !state.levelId || !state.spawned) return;
  state.autoExploreStarted = false;
  state.autoExploreAttempts = 0;
  state.autoExploreRetryAt = 0;
  const ok = await startExplore({ auto: true, reason: "Level ready — exploring…" });
  if (ok) state.autoExploreStarted = true;
}

async function acceptLevelPrompt() {
  const promptDead = document.getElementById("levelPromptDeadEnds");
  if (promptDead) setExcludeDeadEnds(!!promptDead.checked);
  const sug = state.promptSuggestion;
  closeLevelPrompt(false);
  if (!sug) return;

  // Drop old explorer route while switching packs
  state.route = null;
  state.routeGeo = null;
  state.diverted = false;
  state.autoExploreStarted = false;
  state.autoExploreAttempts = 0;
  state.autoExploreRetryAt = 0;
  state.lastGoodLat = null;
  state.lastGoodLon = null;
  clearManeuverHud();
  clearRouteLayers();

  if (sug.existingId) {
    document.getElementById("navHint").textContent = `Switching to ${sug.label}…`;
    await WardAuth.apiFetch("/api/levels/active", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level_id: sug.existingId }),
    });
    state.levelId = sug.existingId;
    state.levelName = sug.label;
    document.getElementById("statLevel").textContent = state.levelName;
    state.outsideM = 0;
    if (sug.existingStatus === "ready") {
      await prepareValhallaForLevel();
      await resumeExploreAfterLevel();
    } else {
      showBuildOverlay(`Building ${sug.label}…`);
      await pollLevelUntilReady(sug.existingId);
    }
    return;
  }

  const body = sug.create;
  document.getElementById("navHint").textContent = `Creating ${sug.label}…`;
  showBuildOverlay(`Building ${sug.label}…`);
  const res = await WardAuth.apiFetch("/api/levels", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: body.name,
      place_query: body.place_query,
      profile: body.profile || "car",
      geofabrik_id: body.geofabrik_id,
      place_bbox: body.place_bbox,
      place_boundary: body.place_boundary,
      place_kind: body.place_kind,
      parent_label: body.parent_label,
      part_label: body.part_label,
      osm_relation_id: body.osm_relation_id,
      osm_admin_level: body.osm_admin_level,
      download_now: true,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    hideBuildOverlay();
    document.getElementById("navHint").textContent =
      data.detail || "Could not create level";
    return;
  }
  const level = data.level;
  state.levelId = level.id;
  state.levelName = level.name || sug.label;
  document.getElementById("statLevel").textContent = state.levelName;
  await WardAuth.apiFetch("/api/levels/active", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level_id: level.id }),
  });
  state.outsideM = 0;
  const jobId = data.job?.id;
  if (jobId) {
    await pollLevelJob(jobId);
  } else {
    await pollLevelUntilReady(level.id);
  }
}

async function pollLevelJob(jobId) {
  showBuildOverlay(`Building ${state.levelName}…`);
  for (let i = 0; i < 300; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    const job = await WardAuth.apiFetch(`/api/jobs/${jobId}`)
      .then((r) => r.json())
      .catch(() => ({}));
    updateBuildOverlay(job);
    const st = job.status || job.state;
    if (st === "done" || st === "finished" || st === "complete") {
      document.getElementById("navBuildFill").style.width = "100%";
      document.getElementById("navBuildPct").textContent = "100%";
      setBuildStage("finish");
      document.getElementById("navBuildMessage").textContent = "Level ready.";
      await new Promise((r) => setTimeout(r, 600));
      hideBuildOverlay();
      document.getElementById("navHint").textContent = `${state.levelName} ready.`;
      await prepareValhallaForLevel();
      await resumeExploreAfterLevel();
      return;
    }
    if (st === "error" || st === "failed") {
      hideBuildOverlay();
      document.getElementById("navHint").textContent =
        job.error || "Level build failed";
      return;
    }
  }
  hideBuildOverlay();
  document.getElementById("navHint").textContent =
    "Build is taking a long time — check Levels.";
}

async function pollLevelUntilReady(levelId) {
  showBuildOverlay(`Building ${state.levelName}…`);
  for (let i = 0; i < 300; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const lv = await WardAuth.apiFetch(`/api/levels/${levelId}`)
      .then((r) => r.json())
      .catch(() => ({}));
    const st = lv.status || "";
    const pct = st === "ready" ? 100 : Math.min(95, 8 + i * 2);
    document.getElementById("navBuildFill").style.width = `${pct}%`;
    document.getElementById("navBuildPct").textContent = `${pct}%`;
    document.getElementById("navBuildMessage").textContent =
      st === "ready" ? "Level ready." : `Status: ${st || "building"}…`;
    document.getElementById("navBuildEta").textContent = "estimating…";
    if (st === "extracting" || st === "downloading") setBuildStage("extract");
    else if (st === "processing" || st === "building") setBuildStage("roads");
    else if (st === "ready") setBuildStage("finish");
    if (st === "ready") {
      await new Promise((r) => setTimeout(r, 500));
      hideBuildOverlay();
      document.getElementById("navHint").textContent = `${state.levelName} ready.`;
      await prepareValhallaForLevel();
      await resumeExploreAfterLevel();
      return;
    }
    if (st === "error") {
      hideBuildOverlay();
      document.getElementById("navHint").textContent =
        lv.error || "Level build failed";
      return;
    }
  }
  hideBuildOverlay();
}

async function trySuggestLevel(kind = "switch") {
  const sug = await WardAuth.apiFetch(
    `/api/navigate/suggest-level?lat=${state.lat}&lon=${state.lon}`
  )
    .then((r) => r.json())
    .catch(() => ({}));
  if (!sug.ok) {
    document.getElementById("navHint").textContent =
      sug.detail ||
      sug.reason ||
      "Outside level — no city suggestion yet. Keep driving.";
    return false;
  }
  return openLevelPrompt(sug, kind);
}

/**
 * On spawn: if there is no level, or GPS is already outside the active level,
 * prompt immediately — do not wait for the 300 m leave corridor.
 */
async function promptIfUnknownOnSpawn() {
  if (!state.navigationActive) return;
  if (!state.spawned || state.promptOpen || state.building) return;

  if (!state.levelId) {
    document.getElementById("navHint").textContent =
      "No level here — looking up a place to generate…";
    await trySuggestLevel("create");
    return;
  }

  const res = await WardAuth.apiFetch(
    `/api/navigate/contains?lat=${state.lat}&lon=${state.lon}&level_id=${state.levelId}`
  );
  const data = await res.json().catch(() => ({}));
  if (data.inside) {
    document.getElementById("navHint").textContent =
      "Spawned. Drive to collect signals. Leave the level by 300 m to auto-load the next.";
    return;
  }
  // Already outside when the drive starts → ask now
  state.outsideM = OUTSIDE_TRIGGER_M;
  document.getElementById("navHint").textContent =
    `Spawned outside ${state.levelName} — suggesting a level…`;
  await trySuggestLevel("create");
}

async function checkOutsideLevel(now) {
  if (!state.navigationActive) return;
  if (!state.spawned || state.promptOpen || state.building) return;
  if (state.containsInFlight) return;
  if (now - state.lastContains < CONTAINS_MS) return;
  state.lastContains = now;
  state.containsInFlight = true;

  try {
    // No level: spawn already prompted instantly. Retry suggest after 300 m
    // only if the first lookup failed or was dismissed for another place.
    if (!state.levelId) {
      if (state.lastOutsideLat == null) {
        state.lastOutsideLat = state.lat;
        state.lastOutsideLon = state.lon;
        return;
      }
      state.outsideM += haversineM(
        state.lastOutsideLat,
        state.lastOutsideLon,
        state.lat,
        state.lon
      );
      state.lastOutsideLat = state.lat;
      state.lastOutsideLon = state.lon;
      document.getElementById("navHint").textContent =
        `No level · ${Math.round(state.outsideM)}/${OUTSIDE_TRIGGER_M} m to retry suggest`;
      if (state.outsideM < OUTSIDE_TRIGGER_M) return;
      const opened = await trySuggestLevel("create");
      if (opened) state.outsideM = 0;
      else state.outsideM = Math.max(0, OUTSIDE_TRIGGER_M - 80);
      return;
    }

    const res = await WardAuth.apiFetch(
      `/api/navigate/contains?lat=${state.lat}&lon=${state.lon}&level_id=${state.levelId}`
    );
    const data = await res.json().catch(() => ({}));
    if (data.inside) {
      state.outsideM = 0;
      state.lastOutsideLat = state.lat;
      state.lastOutsideLon = state.lon;
      return;
    }
    if (state.lastOutsideLat != null) {
      state.outsideM += haversineM(
        state.lastOutsideLat,
        state.lastOutsideLon,
        state.lat,
        state.lon
      );
    }
    state.lastOutsideLat = state.lat;
    state.lastOutsideLon = state.lon;
    document.getElementById("navHint").textContent =
      `Outside ${state.levelName} · ${Math.round(state.outsideM)}/${OUTSIDE_TRIGGER_M} m`;
    if (state.outsideM < OUTSIDE_TRIGGER_M) return;

    const opened = await trySuggestLevel("switch");
    // Only clear distance when the 20s timer actually appears
    if (opened) state.outsideM = 0;
    else state.outsideM = Math.max(0, OUTSIDE_TRIGGER_M - 80);
  } finally {
    state.containsInFlight = false;
  }
}

function moveStep(dtSec, now) {
  if (!state.spawned) return;
  let turn = 0;
  let throttle = 0;
  if (state.keys.has("ArrowLeft") || state.keys.has("a")) turn -= 1;
  if (state.keys.has("ArrowRight") || state.keys.has("d")) turn += 1;
  if (state.keys.has("ArrowUp") || state.keys.has("w")) throttle = 1;
  if (state.keys.has("ArrowDown") || state.keys.has("s")) throttle = -0.35;

  const shift = state.keys.has("Shift");
  const cruise = shift ? 50 : 15;
  const target = cruise * throttle;
  state.speedKmh += (target - state.speedKmh) * Math.min(1, dtSec * 3);
  if (Math.abs(state.speedKmh) < 0.2 && throttle === 0) state.speedKmh = 0;

  state.heading = (state.heading + turn * (shift ? 70 : 45) * dtSec + 360) % 360;
  state.moving = state.speedKmh !== 0 || turn !== 0;

  if (state.speedKmh !== 0) {
    const distM = (state.speedKmh / 3.6) * dtSec;
    const rad = (state.heading * Math.PI) / 180;
    state.lat += (distM * Math.cos(rad)) / 111320;
    state.lon +=
      (distM * Math.sin(rad)) /
      (111320 * Math.cos((state.lat * Math.PI) / 180));
  }

  const shown = Math.abs(state.speedKmh);
  if (Math.abs(shown - state.lastSpeedUi) >= 0.5) {
    state.lastSpeedUi = shown;
    document.getElementById("statSpeed").textContent = shown.toFixed(0);
  }

  if (state.moving) {
    followCamera(now);
    checkOffRoute(now);
    if (state.diverted) {
      clearManeuverHud();
    } else {
      updateManeuverHud();
      updateRouteProgress();
    }
  }
  // Distance only changes while moving; idle uses a longer poll interval
  if (state.moving || now - state.lastContains >= CONTAINS_MS_IDLE) {
    checkOutsideLevel(now);
  }
}

function isDriveInput() {
  return state.keys.size > 0;
}

function wantsFastLoop() {
  return (
    // Live GPS follow needs full rAF so camera/marker lerp actually runs
    (state.followLiveGps && state.spawned) ||
    isDriveInput() ||
    state.speedKmh !== 0 ||
    state.moving ||
    state.spawnMode
  );
}

/** Adaptive quality: pause marker CSS anims when parked; MapLibre stays on-demand */
function setDriveHot(hot) {
  if (state.driveHot === hot) return;
  state.driveHot = hot;
  document.body.classList.toggle("nav-idle", !hot);
  if (!hot && state.map) {
    state.map.repaint = false;
    state.map.triggerRepaint();
  }
}

function cancelSimTimers() {
  if (state.rafId) {
    cancelAnimationFrame(state.rafId);
    state.rafId = 0;
  }
  if (state.idleTimer) {
    clearTimeout(state.idleTimer);
    state.idleTimer = 0;
  }
}

function scheduleSimFrame() {
  if (!state.simActive) return;
  cancelSimTimers();
  if (wantsFastLoop()) {
    state.rafId = requestAnimationFrame(simFrame);
    return;
  }
  // Pre-spawn: sleep until spawn mode / keys. Spawned+parked: slow keep-alive tick.
  if (!state.spawned && !state.spawnMode) return;
  state.idleTimer = setTimeout(() => {
    state.idleTimer = 0;
    state.rafId = requestAnimationFrame(simFrame);
  }, IDLE_TICK_MS);
}

function wakeSimLoop() {
  if (!state.simActive) return;
  if (state.rafId) return;
  cancelSimTimers();
  state.rafId = requestAnimationFrame(simFrame);
}

function setSimActive(on) {
  if (state.simActive === on) return;
  state.simActive = on;
  if (!on) {
    cancelSimTimers();
    setDriveHot(false);
    if (state.map) {
      state.map.repaint = false;
    }
    return;
  }
  state.lastFrameAt = performance.now();
  if (state.map) state.map.triggerRepaint();
  wakeSimLoop();
}

function bindSimVisibility() {
  document.addEventListener("visibilitychange", () => {
    setSimActive(document.visibilityState === "visible");
  });
  const mapEl = document.getElementById("navMap");
  if (mapEl && typeof IntersectionObserver === "function") {
    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries.some((e) => e.isIntersecting && e.intersectionRatio > 0);
        // Tab hidden is handled above; only freeze when map scrolled off-screen
        if (document.visibilityState !== "visible") return;
        setSimActive(visible);
      },
      { threshold: 0.05 }
    );
    io.observe(mapEl);
  }
}

function simFrame(now) {
  state.rafId = 0;
  if (!state.simActive) return;
  const prev = state.lastFrameAt || now;
  const dt = Math.min(0.05, (now - prev) / 1000);
  state.lastFrameAt = now;

  if (state.followLiveGps) {
    pollFollowGps(now);
    // Keep lerping camera between GPS polls (5 Hz backend → smooth HUD)
    if (state.spawned) {
      followCamera(now);
      checkOffRoute(now);
      if (state.diverted) clearManeuverHud();
      else {
        updateManeuverHud();
        updateRouteProgress();
      }
      if (now - state.lastContains >= CONTAINS_MS_IDLE || state.moving) {
        checkOutsideLevel(now);
      }
    }
    setDriveHot(true);
  } else {
    moveStep(dt, now);

    const hot = wantsFastLoop();
    setDriveHot(hot);

    const fixEvery = hot ? FIX_MS : FIX_MS_IDLE;
    if (state.spawned && now - state.lastFix >= fixEvery) {
      state.lastFix = now;
      // Stationary fixes keep radio HUD warm but skip unlock work server-side
      pushFix(hot);
    }
  }

  scheduleSimFrame();
}

async function prepareValhallaForLevel() {
  if (!state.levelId) return null;
  document.getElementById("navHint").textContent =
    "Clipping map pack to this level for Valhalla…";
  const res = await WardAuth.apiFetch("/api/navigate/prepare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level_id: state.levelId, restart: true }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    document.getElementById("navHint").textContent =
      data.detail || "Could not prepare Valhalla extract for this level";
    return null;
  }
  const mb = ((data.active_bytes || 0) / (1024 * 1024)).toFixed(1);
  if (data.clipped || data.valhalla?.restarted) {
    document.getElementById("navHint").textContent =
      `Level clip ready (~${mb} MB). Valhalla is rebuilding tiles — wait, then Start explore.`;
  } else {
    document.getElementById("navHint").textContent =
      `Valhalla extract already matches this level (~${mb} MB).`;
  }
  return data;
}

async function checkValhallaHint() {
  try {
    const res = await WardAuth.apiFetch("/api/navigate/status");
    const data = await res.json();
    const meta = data.active_extract?.meta;
    if (meta?.level_id && state.levelId && meta.level_id !== state.levelId) {
      await prepareValhallaForLevel();
      return false;
    }
    if (!data.valhalla?.ok) {
      document.getElementById("navHint").textContent =
        data.valhalla?.building_hint ||
        "Valhalla still building tiles — wait, then Start explore.";
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

async function startExplore(opts = {}) {
  if (!state.spawned || !state.levelId) return false;
  if (!state.navigationActive && !opts.force) return false;
  if (state.exploreInFlight) return false;
  state.exploreInFlight = true;
  const auto = !!opts.auto;
  try {
    if (!auto) {
      document.getElementById("navHint").textContent = "Checking Valhalla…";
    }
    const ready = await checkValhallaHint();
    if (!ready) {
      if (state.diverted) clearManeuverHud();
      return false;
    }
    document.getElementById("navHint").textContent = auto
      ? opts.reason || "Recalculating…"
      : "Routing via Valhalla…";
    if (state.diverted) clearManeuverHud();
    await pushFix(true);
    const targetKm = Number(document.getElementById("targetKm")?.value) || 5;
    const res = await WardAuth.apiFetch("/api/navigate/explore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        level_id: state.levelId,
        lat: state.lat,
        lon: state.lon,
        heading_deg: state.heading,
        target_km: targetKm,
        exclude_dead_ends: !!state.excludeDeadEnds,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail =
        typeof data.detail === "string"
          ? data.detail
          : Array.isArray(data.detail)
            ? data.detail.map((d) => d.msg || d).join("; ")
            : "Routing failed";
      document.getElementById("navHint").textContent = detail;
      if (state.diverted) clearManeuverHud();
      return false;
    }
    setRoute(data.route);
    const replanBtn = document.getElementById("btnReplan");
    if (replanBtn) replanBtn.disabled = false;
    setNavHint(
      `Explorer route ~${Number(data.route.length_km).toFixed(1)} km · ${data.route.waypoint_count} fog waypoints`
    );
    return true;
  } finally {
    state.exploreInFlight = false;
  }
}

async function resolveLevel() {
  const settings = await WardAuth.apiFetch("/api/settings").then((r) => r.json());
  state.anomalyAlerts =
    settings.anomaly_alerts !== false && settings.anomaly_alerts !== "false";
  state.achievementSounds =
    settings.achievement_sounds !== false &&
    settings.achievement_sounds !== "false";
  syncMuteIcon();
  const anomalyToggle = document.getElementById("toggleAnomaly");
  if (anomalyToggle) anomalyToggle.checked = state.anomalyAlerts;
  if (settings.active_level_id) {
    state.levelId = Number(settings.active_level_id);
  } else {
    const levels = await WardAuth.apiFetch("/api/levels").then((r) => r.json());
    const ready = (levels || []).find((lv) => lv.status === "ready");
    state.levelId = ready ? ready.id : null;
  }
  if (!state.levelId) {
    setNavHint("No level yet — drive to a place to generate one.");
    return;
  }
  const lv = await WardAuth.apiFetch(`/api/levels/${state.levelId}`).then((r) =>
    r.json()
  );
  state.levelName = lv.name || `Level ${state.levelId}`;
  state.levelBoundary = lv.boundary || null;
  document.getElementById("statLevel").textContent = state.levelName;
  if (lv.bbox?.length === 4) {
    state.lon = (lv.bbox[0] + lv.bbox[2]) / 2;
    state.lat = (lv.bbox[1] + lv.bbox[3]) / 2;
  }
  try {
    const prog = await WardAuth.apiFetch("/api/me/progress").then((r) => r.json());
    const xpEl = document.getElementById("statXpLevel");
    if (xpEl && prog?.level != null) xpEl.textContent = String(prog.level);
  } catch {
    /* optional */
  }
}

function initMap() {
  state.webglOk = supportsWebGL();
  loadNavPrefs();
  const night = solarElevation(state.lat, state.lon) < -3;
  state.night = night;
  document.body.dataset.navNight = night ? "1" : "0";

  state.map = new maplibregl.Map({
    container: "navMap",
    style: mapStyleUrl(night),
    center: [state.lon, state.lat],
    zoom: ZOOM_DEFAULT,
    pitch: currentPitch(),
    bearing: 0,
    minZoom: ZOOM_MIN - 0.8,
    maxZoom: ZOOM_MAX + 0.4,
    antialias: false,
    fadeDuration: 0,
    maxTileCacheSize: 48,
    renderWorldCopies: false,
    preserveDrawingBuffer: false,
    // Cap retina cost — still sharp enough for HUD drive; big idle/drive GPU win
    pixelRatio: Math.min(typeof devicePixelRatio === "number" ? devicePixelRatio : 1, 1.5),
    attributionControl: true,
  });
  // Paint on demand (jumpTo / tile loads) — never leave continuous repaint on.
  state.map.repaint = false;
  state.map.addControl(
    new maplibregl.NavigationControl({ visualizePitch: true }),
    "top-right"
  );

  const buildingsToggle = document.getElementById("toggleBuildings");
  if (buildingsToggle) {
    buildingsToggle.checked = state.view3d;
    if (!state.webglOk) buildingsToggle.disabled = true;
  }
  syncViewModeUi();
  syncNavToggleUi();

  state.map.on("load", () => {
    applyRouteThemeColors();
    enableBuildings(state.view3d && state.webglOk);
    bindMapCameraGestures();
  });

  state.map.on("click", (e) => {
    if (!state.spawnMode) return;
    state.lat = e.lngLat.lat;
    state.lon = e.lngLat.lng;
    state.spawned = true;
    state.spawnMode = false;
    state.outsideM = 0;
    state.lastOutsideLat = state.lat;
    state.lastOutsideLon = state.lon;
    state.sessionStartedAt = new Date().toISOString();
    state.sessionUnlockM = 0;
    state.anomalyAlerted = new Set();
    state.anomalyLastToastAt = 0;
    updateUnlockHud();
    updateRadioHud({
      wifi: { seen: 0, new: 0 },
      bt: { seen: 0, new: 0 },
      ble: { seen: 0, new: 0 },
    });
    const spawnBtn = document.getElementById("btnSpawn");
    if (spawnBtn) spawnBtn.textContent = "Respawn";
    const startBtn = document.getElementById("btnStart");
    if (startBtn) startBtn.disabled = !state.levelId;
    setNavHint(
      state.levelId
        ? "Spawned. Checking level coverage…"
        : "Spawned. Looking up a level for this place…"
    );
    document.getElementById("navMap").style.cursor = "";
    ensureMarker();
    state.camLat = state.lat;
    state.camLon = state.lon;
    state.camBearing = state.heading;
    state.camPitch = currentPitch();
    followCamera(performance.now());
    pushFix(true);
    checkValhallaHint();
    wakeSimLoop();
  });
}

function syncViewModeUi() {
  const btn = document.getElementById("btnViewMode");
  const on = !!state.view3d;
  if (btn) {
    // Colorful 3D icon when 3D; grayed 3D icon when 2D
    btn.classList.toggle("is-on", on);
    btn.classList.toggle("is-muted-look", !on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.title = on ? "3D view (tap for 2D)" : "2D view (tap for 3D)";
    if (!state.webglOk) btn.disabled = true;
  }
  const toggle = document.getElementById("toggleBuildings");
  if (toggle) toggle.checked = on;
}

function syncMuteIcon() {
  const btn = document.getElementById("btnMuteSounds");
  if (!btn) return;
  const soundOn = !!state.achievementSounds;
  // Always mute glyph — grayed when sound is on, colorful when muted
  btn.classList.toggle("is-on", !soundOn);
  btn.classList.toggle("is-muted-look", soundOn);
  btn.setAttribute("aria-pressed", soundOn ? "false" : "true");
  btn.title = soundOn ? "Sounds on (tap to mute)" : "Muted (tap to enable)";
}

async function setAchievementSounds(on) {
  state.achievementSounds = !!on;
  syncMuteIcon();
  try {
    await WardAuth.apiFetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ achievement_sounds: state.achievementSounds }),
    });
  } catch (_) {
    /* keep local toggle even if settings POST fails */
  }
}

function setView3d(on) {
  state.view3d = !!on;
  state.buildingsOn = state.view3d && state.webglOk;
  localStorage.setItem(VIEW_3D_KEY, state.view3d ? "1" : "0");
  localStorage.setItem(BUILDINGS_KEY, state.buildingsOn ? "1" : "0");
  syncViewModeUi();
  state.camPitch = currentPitch();
  // Clear any gesture cooldown so a leftover pitchstart can't hold the view
  state.userCamUntil = 0;
  state.userCamActive = false;
  state.userCamGesturePending = false;
  enableBuildings(state.buildingsOn);
  if (state.map) {
    withProgrammaticCam(() => {
      const center =
        state.dispLon != null
          ? [state.dispLon, state.dispLat]
          : state.map.getCenter().toArray();
      state.map.jumpTo({
        center,
        bearing:
          state.dispHeading != null ? state.dispHeading : state.map.getBearing(),
        pitch: state.camPitch,
      });
    });
  }
}

/** @deprecated alias for debug checkbox */
function setBuildingsOn(on) {
  setView3d(on);
}

function bindControls() {
  const dbg = document.getElementById("navDebugToolbar");
  if (dbg) {
    // Always force-hide unless ?debug=1 (CSS display:flex used to ignore [hidden])
    dbg.hidden = !DEBUG_NAV;
    dbg.style.display = DEBUG_NAV ? "" : "none";
  }
  const hint = document.getElementById("navHint");
  if (hint && !DEBUG_NAV) {
    hint.hidden = true;
  }

  document.getElementById("btnNavToggle")?.addEventListener("click", () => {
    toggleNavigation();
  });
  document.getElementById("btnMuteSounds")?.addEventListener("click", () => {
    setAchievementSounds(!state.achievementSounds);
  });
  document.getElementById("btnViewMode")?.addEventListener("click", () => {
    setView3d(!state.view3d);
  });

  document.getElementById("btnSpawn")?.addEventListener("click", () => {
    if (state.followLiveGps) setFollowLiveGps(false);
    state.spawnMode = true;
    document.getElementById("navMap").style.cursor = "crosshair";
    setNavHint("Click the map to spawn.");
    wakeSimLoop();
  });
  document.getElementById("btnFollowGps")?.addEventListener("click", () => {
    setFollowLiveGps(!state.followLiveGps);
  });
  document.getElementById("btnStart")?.addEventListener("click", () => {
    if (!state.navigationActive) state.navigationActive = true;
    syncNavToggleUi();
    startExplore({ force: true });
  });
  document.getElementById("btnReplan")?.addEventListener("click", () => {
    if (!state.navigationActive) state.navigationActive = true;
    syncNavToggleUi();
    startExplore({ force: true, auto: true, reason: "Manual replan" });
  });
  document.getElementById("toggleAnomaly")?.addEventListener("change", (e) => {
    setAnomalyAlerts(!!e.target.checked);
  });
  document.getElementById("toggleDeadEnds")?.addEventListener("change", (e) => {
    setExcludeDeadEnds(!!e.target.checked);
  });
  document.getElementById("toggleBuildings")?.addEventListener("change", (e) => {
    setView3d(!!e.target.checked);
  });
  document.getElementById("levelPromptDeadEnds")?.addEventListener("change", (e) => {
    // Live edit during countdown — persisted on Yes / auto-confirm
    state.excludeDeadEnds = !!e.target.checked;
  });
  window.addEventListener("wardrivrr:theme", () => onSiteThemeChange());
  document.getElementById("levelPromptNo")?.addEventListener("click", () => {
    closeLevelPrompt(true);
    setNavHint("Level load dismissed.");
  });
  document.getElementById("levelPromptYes")?.addEventListener("click", () => {
    acceptLevelPrompt();
  });

  window.addEventListener("keydown", (e) => {
    if (state.followLiveGps) return;
    const k = e.key;
    if (
      [
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Shift",
        "w",
        "a",
        "s",
        "d",
        "W",
        "A",
        "S",
        "D",
      ].includes(k)
    ) {
      e.preventDefault();
      state.keys.add(k.length === 1 ? k.toLowerCase() : k);
      setDriveHot(true);
      wakeSimLoop();
    }
  });
  window.addEventListener("keyup", (e) => {
    const k = e.key;
    state.keys.delete(k.length === 1 ? k.toLowerCase() : k);
    if (k === "Shift") state.keys.delete("Shift");
  });
}

async function boot() {
  await WardAuth.requireAuth();
  await resolveLevel();
  initMap();
  bindControls();
  bindSimVisibility();
  document.body.classList.add("nav-idle");
  if (state.levelId) {
    await prepareValhallaForLevel();
  }
  checkValhallaHint();

  // Car primary path: auto-follow gpsd / live fix, then auto-explore
  const followed = await tryAutoFollowFromGpsd();
  if (!followed && !DEBUG_NAV) {
    setFollowLiveGps(true); // poll until gpsd appears
    setNavHint("Waiting for GPS…");
  }
  // Keep polling for late gpsd lock
  setInterval(() => {
    if (!state.followLiveGps) tryAutoFollowFromGpsd();
  }, 4000);

  state.lastFrameAt = performance.now();
  scheduleSimFrame();

  WardAuth.apiFetch("/api/navigation/active", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ active: true }),
  }).catch(() => {});
}

boot();
