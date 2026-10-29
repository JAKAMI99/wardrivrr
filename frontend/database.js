const COLORS = {
  WIFI: "#00e5ff",
  BLE: "#c084fc",
  BT: "#60a5fa",
  GSM: "#fbbf24",
  LTE: "#f87171",
};

/** Mainland + near-Europe envelope - used until ≥100 networks exist. */
const EUROPE_BOUNDS = [
  [34.5, -12.0], // SW
  [71.5, 42.0], // NE
];

/** OSM serves up to ~19; overzoom two levels past for close inspection. */
const MAP_MAX_ZOOM = 21;
const OSM_NATIVE_ZOOM = 19;

// Default: Europe. After boot, if ≥100 networks exist, fit 100 random (invisible) points.
const map = L.map("map", { zoomControl: true, maxZoom: MAP_MAX_ZOOM }).fitBounds(
  EUROPE_BOUNDS,
  {
    padding: [24, 24],
    animate: false,
  }
);
window.addEventListener("resize", () => map.invalidateSize());
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxNativeZoom: OSM_NATIVE_ZOOM,
  maxZoom: MAP_MAX_ZOOM,
  attribution: "&copy; OpenStreetMap",
}).addTo(map);

function waitForMapSize(timeoutMs = 2500) {
  return new Promise((resolve) => {
    const start = performance.now();
    const tick = () => {
      map.invalidateSize();
      const size = map.getSize();
      if (size.x > 0 && size.y > 0) {
        resolve(true);
        return;
      }
      if (performance.now() - start > timeoutMs) {
        resolve(false);
        return;
      }
      requestAnimationFrame(tick);
    };
    tick();
  });
}

function fitEurope() {
  map.fitBounds(EUROPE_BOUNDS, { padding: [24, 24], animate: false });
  requestAnimationFrame(() => map.invalidateSize());
}

async function fitViewToSample() {
  await waitForMapSize();
  try {
    const res = await WardAuth.apiFetch("/api/explore/view");
    if (!res.ok) {
      console.warn("[database] /api/explore/view failed", res.status);
      fitEurope();
      return;
    }
    const data = await res.json();
    // Need a full 100-point sample before leaving the Europe default
    if (!data.enough || !data.bbox || data.bbox.length !== 4) {
      fitEurope();
      return;
    }
    const [west, south, east, north] = data.bbox.map(Number);
    // Fit so all 100 sample points are on screen (samples themselves are never drawn)
    map.fitBounds(
      [
        [south, west],
        [north, east],
      ],
      { padding: [48, 48], maxZoom: 16, animate: false }
    );
    requestAnimationFrame(() => map.invalidateSize());
  } catch (err) {
    console.warn("[database] view fit failed", err);
    fitEurope();
  }
}

const clusters = L.markerClusterGroup({
  chunkedLoading: true,
  // Uncluster at max zoom so stacked blobs become individual markers
  disableClusteringAtZoom: MAP_MAX_ZOOM,
  spiderfyOnMaxZoom: true,
  // Tighter clusters near max zoom so nearby points separate sooner
  maxClusterRadius: (zoom) => (zoom >= MAP_MAX_ZOOM - 2 ? 40 : 80),
});
map.addLayer(clusters);

const form = document.getElementById("filters");
const banner = document.getElementById("banner");
const statusEl = document.getElementById("status");
const locModeEl = document.getElementById("locMode");

function colorFor(type) {
  return COLORS[type] || "#8e95a0";
}

function circle(lat, lon, type) {
  return L.circleMarker([lat, lon], {
    radius: 7,
    color: colorFor(type),
    weight: 2,
    fillColor: colorFor(type),
    fillOpacity: 0.85,
  });
}

/** Display API ISO datetimes as dd.mm.yyyy (no time). */
function formatDisplayDate(value) {
  if (value == null || value === "") return "-";
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

function formatFilterDate(d) {
  return formatDisplayDate(d);
}

function startOfLocalDay(d) {
  const out = new Date(d);
  out.setHours(0, 0, 0, 0);
  return out;
}

function endOfLocalDay(d) {
  const out = new Date(d);
  out.setHours(23, 59, 59, 999);
  return out;
}

/** Rolling window presets → { after: Date, before: Date }. */
function rangeForPreset(key) {
  const now = new Date();
  const before = endOfLocalDay(now);
  if (key === "48h") {
    return { after: new Date(now.getTime() - 48 * 60 * 60 * 1000), before };
  }
  const days = { "7d": 7, "30d": 30, "182d": 182, "365d": 365, "730d": 730 }[key];
  if (!days) return null;
  const after = startOfLocalDay(new Date(now));
  after.setDate(after.getDate() - (days - 1));
  return { after, before };
}

function applyDatePreset(key) {
  const afterEl = document.getElementById("seenAfter");
  const beforeEl = document.getElementById("seenBefore");
  const presetEl = document.getElementById("datePreset");
  if (!afterEl || !beforeEl || !presetEl) return;
  if (!key) {
    afterEl.value = "";
    beforeEl.value = "";
    delete form.dataset.seenAfterIso;
    return;
  }
  if (key === "custom") {
    delete form.dataset.seenAfterIso;
    return;
  }
  const range = rangeForPreset(key);
  if (!range) return;
  afterEl.value = formatFilterDate(range.after);
  beforeEl.value = formatFilterDate(range.before);
  if (key === "48h") {
    form.dataset.seenAfterIso = range.after.toISOString();
  } else {
    delete form.dataset.seenAfterIso;
  }
}

/** Parse UI filter date dd.mm.yyyy → local Date at midnight, or null if invalid. */
function parseDdMmYyyy(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return null;
  const m = raw.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
  if (!m) return null;
  const day = Number(m[1]);
  const month = Number(m[2]);
  const year = Number(m[3]);
  const d = new Date(year, month - 1, day);
  if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) {
    return null;
  }
  return d;
}

/** Convert filter day to ISO for API: start of local day (seen_after) or end (seen_before). */
function toIsoDayBoundary(value, endOfDay) {
  const d = parseDdMmYyyy(value);
  if (!d) return null;
  if (endOfDay) d.setHours(23, 59, 59, 999);
  else d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

// Names come from over-the-air broadcasts - build with textContent, never HTML.
function popup(props) {
  const rows = [
    ["Name", props.name],
    ["ID", props.network_id],
    ["Vendor", props.vendor],
    ["Type", props.network_type],
    ["Enc", props.encryption],
    ["Date", formatDisplayDate(props.seen_at ?? props.last_seen)],
    ["Signal", props.signal ?? props.avg_signal],
    ["Altitude", props.altitude],
    ["Samples", props.sample_count],
    ["Mode", props.localization_mode],
  ];
  const dl = document.createElement("dl");
  dl.className = "popup";
  for (const [label, value] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value ?? "-";
    dl.append(dt, dd);
  }
  return dl;
}

function queryFromForm() {
  const data = new FormData(form);
  const params = new URLSearchParams();
  const type = data.get("network_type");
  const encryption = data.get("encryption");
  const name = data.get("name")?.trim();
  const networkId = data.get("network_id")?.trim();
  const vendor = data.get("vendor")?.trim();
  if (type) params.set("network_type", type);
  if (encryption) params.set("encryption", encryption);
  if (name) params.set("name", name);
  if (networkId) params.set("network_id", networkId);
  if (vendor) params.set("vendor", vendor);
  if (data.get("exclude_no_ssid")) params.set("exclude_no_ssid", "true");
  const preset = (data.get("date_preset") || "").trim();
  if (preset && preset !== "custom") {
    const range = rangeForPreset(preset);
    if (!range) throw new Error("Unknown date range");
    params.set("seen_after", range.after.toISOString());
    params.set("seen_before", range.before.toISOString());
  } else {
    const afterRaw = data.get("seen_after")?.trim();
    const beforeRaw = data.get("seen_before")?.trim();
    if (form.dataset.seenAfterIso && !afterRaw) {
      params.set("seen_after", form.dataset.seenAfterIso);
    } else if (afterRaw) {
      const after = toIsoDayBoundary(afterRaw, false);
      if (!after) throw new Error("From date must be dd.mm.yyyy");
      params.set("seen_after", after);
    }
    if (beforeRaw) {
      const before = toIsoDayBoundary(beforeRaw, true);
      if (!before) throw new Error("To date must be dd.mm.yyyy");
      params.set("seen_before", before);
    }
  }
  if (data.get("in_view")) {
    const b = map.getBounds();
    params.set("bbox", [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].join(","));
  }
  return params;
}

async function loadVendorFilter() {
  const select = document.getElementById("vendorFilter");
  if (!select) return;
  const prev = select.value;
  try {
    const res = await WardAuth.apiFetch("/api/explore/vendors");
    if (!res.ok) return;
    const data = await res.json();
    const vendors = data.vendors || [];
    select.innerHTML = "";
    const all = document.createElement("option");
    all.value = "";
    all.textContent = vendors.length
      ? `All vendors (${vendors.length})`
      : "All vendors";
    select.append(all);
    for (const v of vendors) {
      const opt = document.createElement("option");
      opt.value = v.vendor;
      const count = v.count != null ? ` · ${v.count}` : "";
      opt.textContent = `${v.label || v.vendor}${count}`;
      select.append(opt);
    }
    if (prev && [...select.options].some((o) => o.value === prev)) {
      select.value = prev;
    }
  } catch (err) {
    console.warn("[database] vendor filter failed", err);
  }
}

async function search(event) {
  event?.preventDefault();
  let params;
  try {
    params = queryFromForm();
  } catch (err) {
    statusEl.textContent = "bad date";
    banner.hidden = false;
    banner.textContent = err.message || "Date must be dd.mm.yyyy";
    return;
  }
  statusEl.textContent = "loading...";
  banner.hidden = true;
  const res = await WardAuth.apiFetch(`/api/explore?${params.toString()}`);
  if (!res.ok) {
    statusEl.textContent = "query failed";
    banner.hidden = false;
    banner.textContent = await res.text();
    return;
  }
  const geo = await res.json();
  clusters.clearLayers();
  const bounds = [];
  geo.features.forEach((feature) => {
    const [lon, lat] = feature.geometry.coordinates;
    const marker = circle(lat, lon, feature.properties.network_type);
    marker.bindPopup(() => popup(feature.properties));
    clusters.addLayer(marker);
    bounds.push([lat, lon]);
  });
  const meta = geo.meta || {};
  statusEl.textContent = `${meta.returned ?? 0} shown · ${meta.matched_networks ?? 0} networks`;
  if (meta.truncated) {
    banner.hidden = false;
    banner.textContent =
      'Result capped. Zoom in and enable "Only current map view", or tighten filters.';
  }
  if (bounds.length && !params.get("bbox")) {
    map.fitBounds(bounds, { padding: [24, 24], maxZoom: 16 });
  }
}

form.addEventListener("submit", search);
const datePresetEl = document.getElementById("datePreset");
const seenAfterEl = document.getElementById("seenAfter");
const seenBeforeEl = document.getElementById("seenBefore");
datePresetEl?.addEventListener("change", () => {
  applyDatePreset(datePresetEl.value);
});
function markCustomDates() {
  if (!datePresetEl) return;
  if (datePresetEl.value && datePresetEl.value !== "custom") {
    datePresetEl.value = "custom";
  } else if (!datePresetEl.value && (seenAfterEl?.value || seenBeforeEl?.value)) {
    datePresetEl.value = "custom";
  }
  delete form.dataset.seenAfterIso;
}
seenAfterEl?.addEventListener("input", markCustomDates);
seenBeforeEl?.addEventListener("input", markCustomDates);
document.getElementById("clear").addEventListener("click", () => {
  form.reset();
  form.network_type.value = "WIFI";
  form.exclude_no_ssid.checked = true;
  if (form.vendor) form.vendor.value = "";
  if (datePresetEl) datePresetEl.value = "";
  delete form.dataset.seenAfterIso;
});
document.getElementById("toggleFilters").addEventListener("click", () => {
  form.classList.toggle("open");
});

async function refreshHealth() {
  try {
    const res = await WardAuth.apiFetch("/api/health");
    const health = await res.json();
    if (!res.ok) {
      statusEl.textContent = "database down";
      return;
    }
    statusEl.textContent = `${health.networks} networks · ${health.samples ?? health.observations} samples`;
    if (health.localization_mode_default) {
      locModeEl.textContent = health.localization_mode_default;
    }
  } catch {
    statusEl.textContent = "api unreachable";
  }
}

async function boot() {
  await WardAuth.requireAuth();
  await refreshHealth();
  await loadVendorFilter();
  await fitViewToSample();
}

boot();
