/* Progress - fog of war map (driven vs never driven), per transport mode */
const params = new URLSearchParams(window.location.search);
const VEHICLE_KEY = "wardrivrr_nav_vehicle";

const MODE_PRESETS = [
  { id: "big_car", label: "Car B-road+" },
  { id: "small_car", label: "Car" },
  { id: "bicycle", label: "Bike" },
  { id: "foot", label: "On foot" },
];

let map = null;
let lockedLayer = null;
let exploredLayer = null;
let boundaryLayer = null;
let levelId = null;
let activeProfile = "small_car";
let lastByProfile = null;
let fitOnce = true;

function fogColors() {
  // Progress uses a light OSM basemap - separate from Drive fog packs
  // (those are tuned for dark MapLibre styles).
  const theme =
    (document.documentElement.getAttribute("data-theme") || "classic").toLowerCase();
  if (theme === "kidcore" || theme === "kawaii") {
    // Bright map: driven = candy pink, never-driven = soft lilac (not near-black)
    return { explored: "#ff2d95", locked: "#9478ad" };
  }
  if (theme === "crt") {
    return { explored: "#00ff66", locked: "#385538" };
  }
  return { explored: "#1a9b6c", locked: "#6f7785" };
}

function fogBoundaryStyle() {
  const theme =
    (document.documentElement.getAttribute("data-theme") || "classic").toLowerCase();
  if (theme === "kidcore" || theme === "kawaii") {
    return {
      color: "#5b2b6b",
      weight: 2,
      opacity: 0.75,
      fill: false,
      dashArray: "6 8",
    };
  }
  if (theme === "crt") {
    return {
      color: "rgba(0,255,102,0.55)",
      weight: 1.5,
      fill: false,
      dashArray: "4 6",
    };
  }
  return {
    color: "rgba(20,28,40,0.45)",
    weight: 1.5,
    fill: false,
    dashArray: "4 6",
  };
}

function syncLegendSwatches(colors) {
  const root = document.documentElement;
  if (!root?.style || !colors) return;
  root.style.setProperty("--progress-fog-explored", colors.explored);
  root.style.setProperty("--progress-fog-locked", colors.locked);
}

function normalizeProfile(profile) {
  const p = String(profile || "small_car").toLowerCase();
  if (p === "car") return "small_car";
  return MODE_PRESETS.some((x) => x.id === p) ? p : "small_car";
}

function readSavedProfile() {
  try {
    const saved = localStorage.getItem(VEHICLE_KEY);
    if (saved) return normalizeProfile(saved);
  } catch (_) {
    /* ignore */
  }
  return "small_car";
}

function showStatus(msg, isError = false) {
  const el = document.getElementById("progressStatus");
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle("error-text", !!isError);
}

async function resolveLevelId() {
  const q = params.get("level");
  if (q && /^\d+$/.test(q)) return Number(q);
  const settings = await WardAuth.apiFetch("/api/settings").then((r) => r.json());
  if (settings.active_level_id) return Number(settings.active_level_id);
  const levels = await WardAuth.apiFetch("/api/levels").then((r) => r.json());
  const ready = (levels || []).find((lv) => lv.status === "ready");
  return ready ? ready.id : null;
}

function paintRoads(data, { refit = false } = {}) {
  if (!map) return;
  if (lockedLayer) map.removeLayer(lockedLayer);
  if (exploredLayer) map.removeLayer(exploredLayer);
  if (boundaryLayer) map.removeLayer(boundaryLayer);

  const colors = fogColors();
  syncLegendSwatches(colors);

  if (data.boundary && data.boundary.type) {
    boundaryLayer = L.geoJSON(data.boundary, {
      style: fogBoundaryStyle(),
    }).addTo(map);
  }

  lockedLayer = L.geoJSON(data.locked, {
    style: {
      color: colors.locked,
      weight: 2.4,
      opacity: 0.95,
      lineCap: "round",
      lineJoin: "round",
    },
    renderer: L.canvas({ padding: 0.5 }),
  }).addTo(map);

  exploredLayer = L.geoJSON(data.explored, {
    style: {
      color: colors.explored,
      weight: 3.1,
      opacity: 1,
      lineCap: "round",
      lineJoin: "round",
    },
    renderer: L.canvas({ padding: 0.5 }),
  }).addTo(map);

  if (!refit && !fitOnce) return;

  const bounds =
    (boundaryLayer && boundaryLayer.getBounds().isValid() && boundaryLayer.getBounds()) ||
    (exploredLayer.getBounds().isValid() && exploredLayer.getBounds()) ||
    (lockedLayer.getBounds().isValid() && lockedLayer.getBounds());
  if (bounds && bounds.isValid()) {
    map.fitBounds(bounds, { padding: [28, 28] });
  } else if (data.bbox && data.bbox.length === 4) {
    map.fitBounds(
      [
        [data.bbox[1], data.bbox[0]],
        [data.bbox[3], data.bbox[2]],
      ],
      { padding: [28, 28] }
    );
  }
  fitOnce = false;
}

function fmtPct(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${n.toFixed(n >= 10 ? 0 : 1)}%`;
}

function renderModeSwitcher() {
  const host = document.getElementById("progressModes");
  if (!host) return;
  host.innerHTML = "";
  for (const mode of MODE_PRESETS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className =
      "progress-mode-btn" + (mode.id === activeProfile ? " is-active" : "");
    btn.dataset.profile = mode.id;
    const pct = lastByProfile?.[mode.id]?.explored_pct;
    btn.innerHTML = `<span class="progress-mode-label">${mode.label}</span><span class="progress-mode-pct">${fmtPct(pct)}</span>`;
    btn.addEventListener("click", () => {
      if (mode.id === activeProfile) return;
      setActiveProfile(mode.id);
    });
    host.append(btn);
  }
}

function renderPctStrip(data) {
  const sub = document.getElementById("progressSub");
  const chip = document.getElementById("progressCompleteChip");
  if (!sub) return;

  const by = data.by_profile || lastByProfile || {};
  lastByProfile = by;
  const parts = MODE_PRESETS.map((m) => {
    const row = by[m.id];
    const pct = fmtPct(row?.explored_pct);
    const active = m.id === activeProfile ? " is-active" : "";
    return `<span class="progress-pct-item${active}">${m.label} ${pct}</span>`;
  });
  sub.innerHTML = parts.join('<span class="progress-pct-sep" aria-hidden="true">·</span>');

  const done = !!(data.level?.complete ?? by.small_car?.complete);
  if (chip) {
    chip.hidden = !done;
    chip.textContent = done ? "Unlocked (Car ≥ 90%)" : "";
  }
  renderModeSwitcher();
}

function setActiveProfile(profileId) {
  activeProfile = normalizeProfile(profileId);
  try {
    localStorage.setItem(VEHICLE_KEY, activeProfile);
  } catch (_) {
    /* ignore */
  }
  loadProgress({ refit: false });
}

async function loadProgress({ refit = true } = {}) {
  if (!levelId) {
    levelId = await resolveLevelId();
  }
  if (!levelId) {
    showStatus(
      "No ready region yet - preload one under Regions, or Drive will offer one by location.",
      true
    );
    return;
  }

  showStatus("Loading fog of war...");
  const q = new URLSearchParams({ profile: activeProfile });
  const res = await WardAuth.apiFetch(
    `/api/levels/${levelId}/roads?${q.toString()}`
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showStatus(data.detail || "Could not load roads", true);
    return;
  }

  document.getElementById("progressTitle").textContent =
    data.level?.name || "Progress";

  if (!map) {
    map = L.map("progressMap", { zoomControl: true, attributionControl: true });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap",
    }).addTo(map);
  }

  paintRoads(data, { refit });
  renderPctStrip(data);

  const s = data.stats || {};
  const modeLabel =
    MODE_PRESETS.find((m) => m.id === activeProfile)?.label || activeProfile;
  showStatus(
    `${modeLabel}: ${s.explored_segments ?? 0} driven · ${s.locked_segments ?? 0} never driven` +
      ` · ${s.explored_km ?? 0} km bright / ${s.locked_km ?? 0} km dark`
  );
  setTimeout(() => map.invalidateSize(), 80);
}

window.addEventListener("wardrivrr:theme", () => {
  if (map) loadProgress({ refit: false });
});

(async () => {
  await WardAuth.requireAuth();
  activeProfile = readSavedProfile();
  renderModeSwitcher();
  await loadProgress({ refit: true });
})();
