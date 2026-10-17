/* Progress — fog of war map (driven vs never driven), theme-coloured */
const params = new URLSearchParams(window.location.search);
let map = null;
let lockedLayer = null;
let exploredLayer = null;
let boundaryLayer = null;

function fogColors() {
  const f = window.WardTheme?.fogPack?.();
  return {
    explored: f?.explored || "#3dffa8",
    locked: f?.locked || "#12161e",
  };
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

function paintRoads(data) {
  if (!map) return;
  if (lockedLayer) map.removeLayer(lockedLayer);
  if (exploredLayer) map.removeLayer(exploredLayer);
  if (boundaryLayer) map.removeLayer(boundaryLayer);

  const colors = fogColors();

  if (data.boundary && data.boundary.type) {
    boundaryLayer = L.geoJSON(data.boundary, {
      style: {
        color: "rgba(255,255,255,0.28)",
        weight: 1.5,
        fill: false,
        dashArray: "4 6",
      },
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
}

async function loadProgress() {
  const levelId = await resolveLevelId();
  if (!levelId) {
    showStatus("No ready level yet — create one under Levels.", true);
    return;
  }

  showStatus("Loading fog of war…");
  const res = await WardAuth.apiFetch(`/api/levels/${levelId}/roads`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showStatus(data.detail || "Could not load roads", true);
    return;
  }

  document.getElementById("progressTitle").textContent =
    data.level?.name || "Progress";
  const s = data.stats || {};
  document.getElementById("progressSub").textContent =
    `${s.explored_km ?? 0} km driven · ${s.locked_km ?? 0} km dark` +
    (data.level?.explored_pct != null
      ? ` · ${Number(data.level.explored_pct).toFixed(1)}%`
      : "");

  if (!map) {
    map = L.map("progressMap", { zoomControl: true, attributionControl: true });
    // Dark basemap so fog contrast matches Drive
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap &copy; CARTO",
    }).addTo(map);
  }

  paintRoads(data);
  showStatus(
    `${s.explored_segments ?? 0} driven segments · ${s.locked_segments ?? 0} never driven`
  );
  setTimeout(() => map.invalidateSize(), 80);
}

window.addEventListener("wardrivrr:theme", () => {
  if (map && lockedLayer) {
    // Re-fetch not needed — just recolour from cache via reload paint
    loadProgress();
  }
});

(async () => {
  await WardAuth.requireAuth();
  await loadProgress();
})();
