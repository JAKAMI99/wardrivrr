const toast = document.getElementById("toast");
let selectedPlace = null;
let searchCity = null;
let areaOptions = [];
let previewMap = null;
let previewLayer = null;
let activeJobId = null;
let prepareJobId = null;
let createdLevelId = null;
let pollTimer = null;
let prepareTimer = null;
let userUnits = "metric";
let placeResults = [];
let prepareMeta = null; // last prepare job result (pack reuse info)
let existingOsmIds = new Set();

function fmt(n) {
  if (n == null || Number.isNaN(Number(n))) return "-";
  return new Intl.NumberFormat().format(n);
}

const COMPLETE_PCT = 90;

function isLevelComplete(lv) {
  if (lv && typeof lv.complete === "boolean") return lv.complete;
  return Number(lv?.explored_pct || 0) >= COMPLETE_PCT;
}

function fmtBytes(n) {
  if (n == null) return "about unknown size";
  const u = ["B", "KB", "MB", "GB"];
  let v = Number(n);
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `~${v.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function packLine(lv) {
  const name = lv.pack_name || lv.geofabrik_name || (lv.geofabrik_id || "").split("/").pop();
  const size = lv.pack_size_bytes != null ? lv.pack_size_bytes : lv.disk_bytes;
  const others = lv.pack_other_levels;
  if (!name && size == null) return null;
  const bits = [];
  if (size != null) bits.push(fmtBytes(size));
  if (name) bits.push(escapeHtml(name));
  let line = bits.join(" · ");
  if (others != null) {
    line +=
      others === 1
        ? " · used in 1 other region"
        : ` · used in ${others} other regions`;
  }
  return line;
}

function fmtEta(sec) {
  if (sec == null || !Number.isFinite(sec)) return "estimating...";
  if (sec <= 0) return "almost done";
  if (sec < 60) return `~${Math.ceil(sec)}s left`;
  const m = Math.floor(sec / 60);
  const s = Math.ceil(sec % 60);
  return `~${m}m ${s}s left`;
}

function fmtArea(km2) {
  if (km2 == null || Number.isNaN(Number(km2))) return "area unknown";
  const v = Number(km2);
  if (userUnits === "imperial") {
    const mi2 = v * 0.386102;
    return `~${mi2 < 10 ? mi2.toFixed(1) : Math.round(mi2)} mi²`;
  }
  return `~${v < 10 ? v.toFixed(1) : Math.round(v)} km²`;
}

function showToast(message, isError = false) {
  toast.hidden = false;
  toast.textContent = message;
  toast.classList.toggle("error", isError);
}

function setMapLoading(loading) {
  const mapEl = document.getElementById("previewMap");
  const overlay = document.getElementById("previewOverlay");
  mapEl?.classList.toggle("is-loading", !!loading);
  if (overlay) overlay.hidden = !loading;
}

function setAreaNextEnabled(on) {
  const btn = document.getElementById("areaNextBtn");
  if (btn) btn.disabled = !on;
}

function goStep(n) {
  document.querySelectorAll(".wizard-pane").forEach((el) => {
    el.hidden = true;
  });
  const pane = document.getElementById(n === "done" ? "stepDone" : `step${n}`);
  if (pane) pane.hidden = false;
  document.querySelectorAll(".wizard-steps span").forEach((s) => {
    const sn = Number(s.dataset.step);
    s.classList.toggle("active", sn === n);
    s.classList.toggle("done", typeof n === "number" && sn < n);
  });
  if (n === 2) {
    requestAnimationFrame(() => {
      ensurePreviewMap();
      paintPreview();
    });
  }
}

function ensurePreviewMap() {
  if (previewMap) {
    previewMap.invalidateSize();
    return;
  }
  previewMap = L.map("previewMap", { zoomControl: true, attributionControl: false });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
  }).addTo(previewMap);
}

function paintPreview(place = selectedPlace) {
  if (!previewMap || !place) return;
  if (previewLayer) {
    previewMap.removeLayer(previewLayer);
    previewLayer = null;
  }
  const boundary = place.boundary;
  if (boundary && boundary.type) {
    previewLayer = L.geoJSON(boundary, {
      style: {
        color: "#00e5ff",
        weight: 2,
        fillColor: "#00e5ff",
        fillOpacity: 0.18,
      },
    }).addTo(previewMap);
    previewMap.fitBounds(previewLayer.getBounds(), { padding: [28, 28] });
  } else {
    previewLayer = L.marker([place.lat, place.lon]).addTo(previewMap);
    previewMap.setView([place.lat, place.lon], 12);
  }
  setTimeout(() => previewMap.invalidateSize(), 50);
}

function isDistrict(p) {
  return (
    p?.place_type === "district" ||
    p?.place_type === "city_part" ||
    p?.place_kind === "district" ||
    p?.place_kind === "city_part"
  );
}

function placeButtonHtml(p, i) {
  return `
    <button type="button" class="level-extract-btn" data-i="${i}">
      <strong>${escapeHtml(p.label)}</strong>
      <span class="muted">${escapeHtml(p.display_name || "")}</span>
    </button>`;
}

function bindPlaceButtons(box) {
  box.querySelectorAll(".level-extract-btn").forEach((btn) => {
    btn.addEventListener("click", () => beginPrepare(placeResults[Number(btn.dataset.i)]));
  });
}

async function beginPrepare(city) {
  if (!city?.map_pack?.id) {
    showToast("No map pack for this place", true);
    return;
  }
  if (prepareTimer) {
    clearInterval(prepareTimer);
    prepareTimer = null;
  }
  searchCity = city;
  selectedPlace = null;
  areaOptions = [];
  setAreaNextEnabled(false);
  document.getElementById("areaChoices").hidden = true;
  document.getElementById("areaChoices").innerHTML = "";
  document.getElementById("previewTitle").textContent = city.label;
  document.getElementById("previewSub").textContent = "";
  document.getElementById("prepareStatus").textContent = "Starting download...";
  document.getElementById("prepareFill").style.width = "2%";
  document.getElementById("preparePct").textContent = "0%";
  document.getElementById("prepareEta").textContent = "estimating...";
  setMapLoading(true);
  goStep(2);
  ensurePreviewMap();
  paintPreview(city);

  const res = await WardAuth.apiFetch("/api/levels/places/prepare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      lat: city.lat,
      lon: city.lon,
      name: city.name,
      geofabrik_id: city.map_pack.id,
      population: city.population,
      bbox: city.bbox,
      parent_label: city.label,
      country_code: city.country_code,
      geoname_id: city.geoname_id,
    }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    setMapLoading(false);
    document.getElementById("previewSub").textContent =
      body.detail || "Could not prepare map data";
    showToast(body.detail || "Prepare failed", true);
    return;
  }
  prepareJobId = body.job?.id;
  if (!prepareJobId) {
    setMapLoading(false);
    showToast("No prepare job queued", true);
    return;
  }
  prepareTimer = setInterval(pollPrepareJob, 400);
  pollPrepareJob();
}

async function pollPrepareJob() {
  if (!prepareJobId) return;
  const res = await WardAuth.apiFetch(`/api/jobs/${prepareJobId}`);
  const job = await res.json().catch(() => ({}));
  if (!res.ok) return;
  const result = job.result || {};
  const progress = Math.max(0, Math.min(1, Number(job.progress) || 0));
  const pct = Math.round(progress * 100);
  document.getElementById("prepareFill").style.width = `${pct}%`;
  document.getElementById("preparePct").textContent = `${pct}%`;
  document.getElementById("prepareStatus").textContent =
    result.message || (job.status === "queued" ? "Waiting in queue..." : "Working...");
  document.getElementById("prepareEta").textContent = fmtEta(result.eta_seconds);

  if (job.status === "done") {
    clearInterval(prepareTimer);
    prepareTimer = null;
    prepareJobId = null;
    document.getElementById("prepareFill").style.width = "100%";
    document.getElementById("preparePct").textContent = "100%";
    await showAreaChoices(result);
    return;
  }
  if (job.status === "error") {
    clearInterval(prepareTimer);
    prepareTimer = null;
    prepareJobId = null;
    setMapLoading(false);
    document.getElementById("previewSub").textContent =
      job.error || "Prepare failed";
    showToast(job.error || "Prepare failed", true);
  }
}

async function showAreaChoices(result) {
  setMapLoading(false);
  prepareMeta = result;
  await refreshExistingLevels();
  const city = result.city;
  const districts = result.districts || [];
  areaOptions = [];
  if (city) areaOptions.push(city);
  areaOptions.push(...districts);

  const box = document.getElementById("areaChoices");
  if (!areaOptions.length) {
    box.hidden = false;
    box.innerHTML = `<p class="muted">No exact outline found for this place. You can still continue with the map pack area after going back.</p>`;
    document.getElementById("previewSub").textContent = "No outline available";
    return;
  }

  let html = "";
  if (city) {
    html += `<p class="area-choices-heading muted">Whole city</p>`;
    html += areaChoiceHtml(city, 0);
  }
  if (districts.length) {
    html += `<p class="area-choices-heading muted">Districts</p>`;
    districts.forEach((d, i) => {
      html += areaChoiceHtml(d, (city ? 1 : 0) + i);
    });
  }
  box.innerHTML = html;
  box.hidden = false;
  document.getElementById("previewSub").textContent =
    "Pick the whole city or a district - boundary shows on the map first";
  box.querySelectorAll("[data-area-i]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      selectAreaOption(Number(btn.dataset.areaI));
    });
  });
  // Pre-select first available (not already owned)
  const firstFree = areaOptions.findIndex(
    (p) => p.osm_relation_id == null || !existingOsmIds.has(String(p.osm_relation_id))
  );
  if (firstFree >= 0) selectAreaOption(firstFree);
}

function areaChoiceHtml(p, i) {
  const kind = isDistrict(p) ? "District" : "Whole city";
  const owned =
    p.osm_relation_id != null && existingOsmIds.has(String(p.osm_relation_id));
  return `
    <button type="button" class="area-choice-btn ${owned ? "is-owned" : ""}" data-area-i="${i}" ${
      owned ? "disabled" : ""
    }>
      <strong>${escapeHtml(p.label)}</strong>
      <span>${
        owned
          ? "Already in your regions"
          : `${escapeHtml(kind)} · ${escapeHtml(fmtArea(p.area_km2))}`
      }</span>
    </button>`;
}

async function selectAreaOption(index) {
  const place = areaOptions[index];
  if (!place) return;
  selectedPlace = { ...place };
  document.querySelectorAll(".area-choice-btn").forEach((btn) => {
    btn.classList.toggle("is-selected", Number(btn.dataset.areaI) === index);
  });
  setFixedLevelName(selectedPlace.label);
  document.getElementById("previewTitle").textContent = selectedPlace.label;
  document.getElementById("previewSub").textContent = isDistrict(selectedPlace)
    ? "Loading district boundary..."
    : "Whole-city boundary - this will be your playable region";
  fillConfirm();
  setAreaNextEnabled(false);
  ensurePreviewMap();

  if (selectedPlace.boundary && selectedPlace.boundary.type) {
    selectedPlace.boundary_approximate = false;
    paintPreview();
    document.getElementById("previewSub").textContent = isDistrict(selectedPlace)
      ? `District boundary · ${fmtArea(selectedPlace.area_km2)}`
      : `City boundary · ${fmtArea(selectedPlace.area_km2)}`;
    setAreaNextEnabled(true);
    return;
  }

  paintPreview();
  try {
    const params = new URLSearchParams();
    if (selectedPlace.osm_relation_id != null) {
      params.set("osm_relation_id", String(selectedPlace.osm_relation_id));
    } else {
      params.set("lat", String(selectedPlace.lat));
      params.set("lon", String(selectedPlace.lon));
      if (selectedPlace.name) params.set("name", selectedPlace.name);
      if (selectedPlace.map_pack?.id) params.set("geofabrik_id", selectedPlace.map_pack.id);
    }
    const bRes = await WardAuth.apiFetch(`/api/levels/places/boundary?${params}`);
    const bData = await bRes.json().catch(() => ({}));
    if (bRes.ok && bData.boundary) {
      selectedPlace.boundary = bData.boundary;
      selectedPlace.boundary_approximate = false;
      if (bData.bbox) selectedPlace.bbox = bData.bbox;
      document.getElementById("previewSub").textContent = isDistrict(selectedPlace)
        ? `District boundary · ${fmtArea(selectedPlace.area_km2)}`
        : `City boundary · ${fmtArea(selectedPlace.area_km2)}`;
      paintPreview();
      setAreaNextEnabled(true);
    } else {
      document.getElementById("previewSub").textContent =
        bData.detail || "Could not load boundary";
      showToast(bData.detail || "Boundary missing", true);
    }
  } catch {
    document.getElementById("previewSub").textContent = "Could not load boundary";
  }
}

async function searchPlaces(e) {
  e?.preventDefault();
  const q = document.getElementById("placeQuery").value.trim();
  if (!q) return;
  const box = document.getElementById("placeResults");
  box.innerHTML = `<p class="muted">Searching places...</p>`;
  const res = await WardAuth.apiFetch(
    `/api/levels/places/search?q=${encodeURIComponent(q)}`
  );
  const data = await res.json().catch(() => []);
  if (!res.ok) {
    box.innerHTML = `<p class="muted">${escapeHtml(data.detail || "Search failed")}</p>`;
    return;
  }
  if (!data.length) {
    box.innerHTML = `<p class="muted">No places found. Try "Berlin, Germany".</p>`;
    return;
  }
  placeResults = data.slice();
  box.innerHTML = placeResults.map((p, i) => placeButtonHtml(p, i)).join("");
  bindPlaceButtons(box);
}

function setFixedLevelName(label) {
  const name = label || "-";
  document.getElementById("levelName").value = name === "-" ? "" : name;
  const el = document.getElementById("levelNameDisplay");
  if (el) el.textContent = name;
}

function fillConfirm() {
  if (!selectedPlace) return;
  const pack = selectedPlace.map_pack || prepareMeta?.map_pack || {};
  const area = selectedPlace.area_km2 != null ? ` (${fmtArea(selectedPlace.area_km2)})` : "";
  document.getElementById("confirmPlace").textContent =
    `Preload region: ${selectedPlace.label}${area}`;
  const packId = pack.id || prepareMeta?.extract_id || "";
  const packName = pack.name || packId.split("/").pop() || "regional pack";
  const size = pack.size_bytes != null ? fmtBytes(pack.size_bytes) : null;
  const usedBy = prepareMeta?.pack_levels_count;
  let sizeLine = `Map data comes from ${packName}`;
  if (size) sizeLine += ` (${size})`;
  if (usedBy != null) {
    sizeLine +=
      usedBy === 0
        ? " - not used by any of your regions yet"
        : ` - already used by ${usedBy} of your region${usedBy === 1 ? "" : "s"}`;
  }
  sizeLine += ".";
  document.getElementById("confirmSize").textContent = sizeLine;
  document.getElementById("confirmTech").textContent = packId
    ? `Geofabrik extract: ${packId}`
    : "Map pack resolved automatically.";
}

async function refreshExistingLevels() {
  try {
    const data = await WardAuth.apiFetch("/api/levels").then((r) => r.json());
    existingOsmIds = new Set(
      (data || [])
        .filter((lv) => lv.osm_relation_id != null && lv.status !== "error")
        .map((lv) => String(lv.osm_relation_id))
    );
  } catch {
    existingOsmIds = new Set();
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setStage(stage) {
  const order = ["extract", "roads", "finish"];
  const mapped = stage === "download" ? "extract" : stage;
  const idx = order.indexOf(mapped === "done" ? "finish" : mapped);
  document.querySelectorAll("#stageList li").forEach((li) => {
    const si = order.indexOf(li.dataset.stage);
    li.classList.toggle("active", si === idx);
    li.classList.toggle("done", idx >= 0 && si < idx);
  });
}

async function pollJob() {
  if (!activeJobId) return;
  const res = await WardAuth.apiFetch(`/api/jobs/${activeJobId}`);
  const job = await res.json().catch(() => ({}));
  if (!res.ok) return;

  const result = job.result || {};
  const progress = Math.max(0, Math.min(1, Number(job.progress) || 0));
  const pct = Math.round(progress * 100);
  document.getElementById("progressFill").style.width = `${pct}%`;
  document.getElementById("progressPct").textContent = `${pct}%`;
  document.getElementById("progressMessage").textContent =
    result.message || (job.status === "queued" ? "Waiting in queue..." : "Working...");
  document.getElementById("progressEta").textContent = fmtEta(result.eta_seconds);
  if (result.stage) setStage(result.stage);

  if (job.status === "done") {
    clearInterval(pollTimer);
    pollTimer = null;
    document.getElementById("progressFill").style.width = "100%";
    document.getElementById("doneText").textContent =
      `${document.getElementById("levelName").value} is ready.`;
    goStep("done");
    document.getElementById("stepDone").classList.add("celebrate");
    loadLevels();
    return;
  }
  if (job.status === "error") {
    clearInterval(pollTimer);
    pollTimer = null;
    showToast(job.error || "Build failed", true);
    goStep(4);
  }
}

async function generateLevel() {
  if (!selectedPlace?.map_pack?.id) {
    showToast("Pick a place first", true);
    return;
  }
  const name = selectedPlace.label;
  setFixedLevelName(name);
  goStep(5);
  document.getElementById("progressTitle").textContent = `Building ${name}...`;
  document.getElementById("progressFill").style.width = "2%";
  setStage("extract");

  const payload = {
    name,
    place_query: selectedPlace.place_query || selectedPlace.label,
    // Default Navigate mode only - map imports the full playable graph
    profile: "small_car",
    geofabrik_id: selectedPlace.map_pack.id,
    place_bbox: selectedPlace.bbox,
    place_boundary: selectedPlace.boundary,
    download_now: true,
    place_kind: isDistrict(selectedPlace) ? "district" : "city",
    geoname_id: selectedPlace.geoname_id ?? null,
    parent_geoname_id: selectedPlace.parent_geoname_id ?? null,
    parent_label: selectedPlace.parent_label ?? null,
    part_label: selectedPlace.part_label ?? null,
    osm_relation_id: selectedPlace.osm_relation_id ?? null,
    osm_admin_level: selectedPlace.osm_admin_level ?? null,
  };
  const res = await WardAuth.apiFetch("/api/levels", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(body.detail || "Could not start", true);
    goStep(4);
    return;
  }
  createdLevelId = body.level?.id;
  activeJobId = body.job?.id;
  if (!activeJobId) {
    showToast("Region created but no job queued", true);
    return;
  }
  pollTimer = setInterval(pollJob, 500);
  pollJob();
}

function fmtPct(n) {
  if (n == null || Number.isNaN(Number(n))) return "-";
  return `${Number(n).toFixed(1)}%`;
}

function levelCardHtml(lv, activeId, { nested = false } = {}) {
  const isActive = activeId && String(lv.id) === activeId;
  const title = lv.name || lv.place_query;
  const kind = isDistrict(lv)
    ? `<em class="place-kind">District</em>`
    : "";
  const pack = packLine(lv);
  const done = isLevelComplete(lv);
  const placeHint =
    lv.place_query && lv.place_query !== title
      ? `<p class="muted level-place-hint">${escapeHtml(lv.place_query)}</p>`
      : "";
  return `
    <article class="level-card ${isActive ? "active" : ""} ${nested ? "is-part" : ""} ${done ? "is-complete" : ""}">
      <header>
        <h3 class="level-card-title">
          <span class="level-card-name">${kind}${escapeHtml(title)}</span>
        </h3>
        <span class="level-status-stack">
          ${done ? `<span class="level-complete-badge" title="≥ ${COMPLETE_PCT}% roads unlocked">Complete</span>` : ""}
          <span class="level-status status-${lv.status}">${lv.status}</span>
        </span>
      </header>
      <p class="muted level-mode-line">Vehicle mode -> Drive</p>
      ${placeHint}
      <ul class="level-stats">
        <li>${fmtPct(lv.explored_pct)} explored${done ? " · done" : ""}</li>
        <li>${fmt(lv.road_km?.toFixed?.(1) ?? lv.road_km)} km roads</li>
        ${pack ? `<li>${pack}</li>` : ""}
        <li>${fmt(lv.networks_count)} networks</li>
      </ul>
      ${lv.error ? `<p class="error-text">${escapeHtml(lv.error)}</p>` : ""}
      <div class="tools-row">
        <a class="btn btn-primary ${lv.status !== "ready" ? "is-disabled" : ""}" href="${
    lv.status === "ready" ? `/progress?level=${lv.id}` : "#"
  }" ${lv.status !== "ready" ? 'aria-disabled="true"' : ""}>Map</a>
        <button class="btn" data-load="${lv.id}" ${
    lv.status !== "ready" ? "disabled" : ""
  }>Use</button>
        <button class="btn" data-del="${lv.id}">Delete</button>
      </div>
    </article>`;
}

function groupLevels(levels) {
  const groups = new Map();
  const ungrouped = [];

  for (const lv of levels) {
    const parentGn = lv.parent_geoname_id;
    const ownGn = lv.geoname_id;
    const isPart = isDistrict(lv);
    let key = null;
    let label = null;
    if (isPart && parentGn != null) {
      key = `g:${parentGn}`;
      label = lv.parent_label || "City";
    } else if (!isPart && ownGn != null) {
      key = `g:${ownGn}`;
      label = lv.name || lv.place_query || "City";
    } else if (isPart && lv.parent_label) {
      key = `n:${String(lv.parent_label).toLowerCase()}`;
      label = lv.parent_label;
    }

    if (!key) {
      ungrouped.push(lv);
      continue;
    }
    if (!groups.has(key)) {
      groups.set(key, { key, label, city: null, parts: [] });
    }
    const g = groups.get(key);
    if (isPart) g.parts.push(lv);
    else g.city = lv;
    if (!isPart && (lv.name || lv.place_query)) g.label = lv.name || lv.place_query;
  }

  // Only treat as a menu when there is a city + parts, or multiple parts
  const menus = [];
  const flat = [...ungrouped];
  for (const g of groups.values()) {
    if (g.city && g.parts.length) {
      menus.push(g);
    } else if (!g.city && g.parts.length > 1) {
      menus.push(g);
    } else if (g.city && !g.parts.length) {
      flat.push(g.city);
    } else if (g.parts.length === 1) {
      flat.push(g.parts[0]);
    }
  }
  menus.sort((a, b) => String(a.label).localeCompare(String(b.label)));
  flat.sort((a, b) => Number(b.id) - Number(a.id));
  return { menus, flat };
}

function bindLevelActions(el) {
  el.querySelectorAll("[data-load]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await WardAuth.apiFetch("/api/levels/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ level_id: Number(btn.dataset.load) }),
      });
      showToast("Region active");
      loadLevels();
    });
  });
  el.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!window.confirm("Delete this region?")) return;
      await WardAuth.apiFetch(`/api/levels/${btn.dataset.del}`, { method: "DELETE" });
      loadLevels();
    });
  });
  el.querySelectorAll("[data-toggle-group]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const group = btn.closest(".level-group");
      if (!group) return;
      group.classList.toggle("open");
      btn.setAttribute("aria-expanded", group.classList.contains("open") ? "true" : "false");
    });
  });
}

async function loadLevels() {
  const res = await WardAuth.apiFetch("/api/levels");
  const data = await res.json().catch(() => []);
  const el = document.getElementById("levelsList");
  if (!res.ok) {
    el.textContent = data.detail || "Failed to load regions";
    return;
  }
  if (!data.length) {
    el.innerHTML = `<p class="muted">No regions yet - preload a place above, or let Drive offer one by location.</p>`;
    return;
  }
  const settings = await WardAuth.apiFetch("/api/settings").then((r) => r.json());
  const activeId = settings.active_level_id ? String(settings.active_level_id) : null;
  const { menus, flat } = groupLevels(data);

  const menuHtml = menus
    .map((g) => {
      const cityPct = g.city?.explored_pct;
      const partPcts = g.parts.map((p) => Number(p.explored_pct) || 0);
      const summaryPct =
        cityPct != null
          ? fmtPct(cityPct)
          : partPcts.length
            ? fmtPct(partPcts.reduce((a, b) => a + b, 0) / partPcts.length)
            : "-";
      const districtsDone = g.parts.filter((p) => isLevelComplete(p)).length;
      const districtsTotal = g.parts.length;
      const districtLine =
        districtsTotal > 0
          ? `${districtsDone}/${districtsTotal} district${districtsTotal === 1 ? "" : "s"} complete`
          : "";
      const cityDone = g.city && isLevelComplete(g.city);
      const hasActive =
        (g.city && activeId && String(g.city.id) === activeId) ||
        g.parts.some((p) => activeId && String(p.id) === activeId);
      return `
      <section class="level-group ${hasActive ? "has-active" : ""} ${cityDone || districtsDone === districtsTotal ? "is-complete" : ""} open">
        <button type="button" class="level-group-toggle" data-toggle-group aria-expanded="true">
          <span class="level-group-title">${escapeHtml(g.label)}${cityDone || (districtsTotal && districtsDone === districtsTotal) ? ' <span class="level-complete-badge">Complete</span>' : ""}</span>
          <span class="muted">${districtLine || `${g.parts.length} part${g.parts.length === 1 ? "" : "s"}`} · ${summaryPct} explored</span>
        </button>
        <div class="level-group-body">
          ${g.city ? levelCardHtml(g.city, activeId) : ""}
          ${g.parts.map((p) => levelCardHtml(p, activeId, { nested: true })).join("")}
        </div>
      </section>`;
    })
    .join("");

  el.innerHTML =
    menuHtml + flat.map((lv) => levelCardHtml(lv, activeId)).join("");
  bindLevelActions(el);
}

function resetWizard() {
  selectedPlace = null;
  searchCity = null;
  areaOptions = [];
  createdLevelId = null;
  activeJobId = null;
  prepareJobId = null;
  if (pollTimer) clearInterval(pollTimer);
  if (prepareTimer) clearInterval(prepareTimer);
  pollTimer = null;
  prepareTimer = null;
  document.getElementById("placeResults").innerHTML = "";
  document.getElementById("areaChoices").innerHTML = "";
  document.getElementById("areaChoices").hidden = true;
  setMapLoading(false);
  setAreaNextEnabled(false);
  document.getElementById("stepDone").classList.remove("celebrate");
  goStep(1);
}

document.getElementById("searchForm").addEventListener("submit", searchPlaces);
document.querySelectorAll("[data-next]").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.disabled) return;
    if (Number(btn.dataset.next) === 3 && !selectedPlace?.boundary) {
      showToast("Pick an area and wait for the boundary first", true);
      return;
    }
    goStep(Number(btn.dataset.next));
  });
});
document.querySelectorAll("[data-back]").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (prepareTimer) {
      clearInterval(prepareTimer);
      prepareTimer = null;
    }
    goStep(Number(btn.dataset.back));
  });
});
document.getElementById("generateBtn").addEventListener("click", generateLevel);
document.getElementById("doneAnother").addEventListener("click", resetWizard);
document.getElementById("doneLoad").addEventListener("click", async () => {
  if (!createdLevelId) return;
  await WardAuth.apiFetch("/api/levels/active", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level_id: createdLevelId }),
  });
  showToast("Region active");
  loadLevels();
  document.getElementById("regionsListSection")?.scrollIntoView({ behavior: "smooth" });
});

(async () => {
  await WardAuth.requireAuth();
  try {
    const settings = await WardAuth.apiFetch("/api/settings").then((r) => r.json());
    userUnits = settings.units === "imperial" ? "imperial" : "metric";
  } catch {
    userUnits = "metric";
  }
  goStep(1);
  loadLevels();
})();
