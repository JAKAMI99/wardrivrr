const params = new URLSearchParams(window.location.search);
let map = null;
let lockedLayer = null;
let exploredLayer = null;
let boundaryLayer = null;

function showStatus(msg, isError = false) {
  const el = document.getElementById("discoverStatus");
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

function paintRoads(data) {
  if (lockedLayer) map.removeLayer(lockedLayer);
  if (exploredLayer) map.removeLayer(exploredLayer);
  if (boundaryLayer) map.removeLayer(boundaryLayer);

  if (data.boundary && data.boundary.type) {
    boundaryLayer = L.geoJSON(data.boundary, {
      style: {
        color: "rgba(255,255,255,0.35)",
        weight: 1.5,
        fill: false,
        dashArray: "4 6",
      },
    }).addTo(map);
  }

  // Soft coral for locked (clearer than grey, less harsh than pure red on OSM)
  lockedLayer = L.geoJSON(data.locked, {
    style: {
      color: "#e25555",
      weight: 2,
      opacity: 0.72,
      lineCap: "round",
      lineJoin: "round",
    },
    renderer: L.canvas({ padding: 0.5 }),
  }).addTo(map);

  exploredLayer = L.geoJSON(data.explored, {
    style: {
      color: "#2ad48a",
      weight: 2.75,
      opacity: 0.95,
      lineCap: "round",
      lineJoin: "round",
    },
    renderer: L.canvas({ padding: 0.5 }),
  }).addTo(map);

  const bounds =
    (boundaryLayer && boundaryLayer.getBounds().isValid() && boundaryLayer.getBounds()) ||
    (lockedLayer.getBounds().isValid() && lockedLayer.getBounds()) ||
    (exploredLayer.getBounds().isValid() && exploredLayer.getBounds());
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
}

async function loadDiscover() {
  const levelId = await resolveLevelId();
  if (!levelId) {
    showStatus("No ready region yet — preload one under Regions, or Drive will offer one by location.", true);
    return;
  }

  showStatus("Loading road grid…");
  const res = await WardAuth.apiFetch(`/api/levels/${levelId}/roads`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showStatus(data.detail || "Could not load roads", true);
    return;
  }

  document.getElementById("discoverTitle").textContent = data.level?.name || "Discover";
  const s = data.stats || {};
  document.getElementById("discoverSub").textContent =
    `${s.explored_km ?? 0} km explored · ${s.locked_km ?? 0} km locked` +
    (data.level?.explored_pct != null
      ? ` · ${Number(data.level.explored_pct).toFixed(1)}%`
      : "");

  if (!map) {
    map = L.map("discoverMap", { zoomControl: true, attributionControl: true });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap",
    }).addTo(map);
  }

  paintRoads(data);
  showStatus(
    `${s.explored_segments ?? 0} explored segments · ${s.locked_segments ?? 0} locked`
  );
  setTimeout(() => map.invalidateSize(), 80);
}

(async () => {
  await WardAuth.requireAuth();
  await loadDiscover();
})();
