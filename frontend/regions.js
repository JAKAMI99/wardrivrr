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
let areaSelectSeq = 0;
let preparePollInFlight = false;
let areaChoicesGen = 0;

function fmt(n) {
  if (n == null || Number.isNaN(Number(n))) return "-";
  return new Intl.NumberFormat().format(n);
}

const COMPLETE_PCT = 90;

const MODE_PRESETS = [
  { id: "big_car", label: "Car B-road+" },
  { id: "small_car", label: "Car" },
  { id: "bicycle", label: "Bike" },
  { id: "foot", label: "On foot" },
];

function isLevelComplete(lv) {
  const car = lv?.by_profile?.small_car;
  if (car && typeof car.complete === "boolean") return car.complete;
  if (lv && typeof lv.complete === "boolean") return lv.complete;
  return Number(lv?.explored_pct || 0) >= COMPLETE_PCT;
}

function levelByProfile(lv) {
  return lv?.by_profile && typeof lv.by_profile === "object" ? lv.by_profile : {};
}

function aggregateByProfile(levels) {
  const ready = (levels || []).filter((lv) => lv && lv.status === "ready");
  const out = {};
  for (const mode of MODE_PRESETS) {
    const rows = ready
      .map((lv) => levelByProfile(lv)[mode.id])
      .filter(Boolean);
    if (!rows.length) {
      out[mode.id] = { explored_pct: 0, complete: false, label: mode.label };
      continue;
    }
    const pct =
      rows.reduce((a, r) => a + (Number(r.explored_pct) || 0), 0) / rows.length;
    out[mode.id] = {
      explored_pct: pct,
      complete: pct >= COMPLETE_PCT,
      label: mode.label,
    };
  }
  return out;
}

function modeBarsHtml(byProfile) {
  const by = byProfile || {};
  return `<div class="level-mode-bars" aria-label="Explored by drive mode">
    ${MODE_PRESETS.map((mode) => {
      const row = by[mode.id] || {};
      const pct = Math.max(0, Math.min(100, Number(row.explored_pct) || 0));
      const done = !!(row.complete || pct >= COMPLETE_PCT);
      return `<div class="level-mode-bar${done ? " is-complete" : ""}" data-mode="${escapeHtml(mode.id)}">
        <div class="level-mode-bar-meta">
          <span class="level-mode-bar-label">${escapeHtml(mode.label)}</span>
          <span class="level-mode-bar-pct">${fmtPct(pct)}</span>
        </div>
        <div class="level-mode-bar-track" role="progressbar" aria-valuenow="${pct.toFixed(0)}" aria-valuemin="0" aria-valuemax="100" aria-label="${escapeHtml(mode.label)} explored">
          <div class="level-mode-bar-fill" style="width:${pct}%"></div>
        </div>
      </div>`;
    }).join("")}
  </div>`;
}

/** Catalog place → stable key for matching loaded levels */
function partMatchKey(p) {
  if (!p) return null;
  if (p.osm_relation_id != null) return `osm:${p.osm_relation_id}`;
  const n = String(p.name || p.label || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
  return n ? `n:${n}` : null;
}

const unloadedPlaceByKey = new Map();

function unloadedRowHtml(place, key) {
  unloadedPlaceByKey.set(key, place);
  const title = place.label || place.name || "Sub-region";
  return `
    <article class="level-card is-part is-unloaded is-minimal">
      <header>
        <h3 class="level-card-title">
          <span class="level-card-name"><em class="place-kind place-kind-sub">Sub-region</em>${escapeHtml(title)}</span>
        </h3>
        <button type="button" class="btn level-generate-btn" data-generate="${escapeHtml(key)}" data-kidcore-skip>Generate</button>
      </header>
    </article>`;
}

function unloadedPartsForGroup(g, catalogParts) {
  const loadedKeys = new Set(
    (g.parts || [])
      .filter((p) => p.status !== "error")
      .map(partMatchKey)
      .filter(Boolean)
  );
  return (catalogParts || []).filter((p) => {
    const k = partMatchKey(p);
    return k && !loadedKeys.has(k);
  });
}

function subTallyHtml(complete, progressing, unloaded) {
  const unload =
    unloaded == null || Number.isNaN(Number(unloaded))
      ? "—"
      : String(unloaded);
  return `<p class="level-sub-tally" title="Completed / progressing / unloaded sub-regions">
    <span class="tally-done">${complete}</span> completed,
    <span class="tally-open">${progressing}</span> progressing,
    <span class="tally-miss">${escapeHtml(unload)}</span> unloaded
  </p>`;
}

function levelCenter(lv) {
  const bbox = lv?.bbox;
  if (Array.isArray(bbox) && bbox.length >= 4) {
    const [w, s, e, n] = bbox.map(Number);
    if ([w, s, e, n].every((x) => Number.isFinite(x))) {
      return { lat: (s + n) / 2, lon: (w + e) / 2 };
    }
  }
  return null;
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

function isCityLevel(p) {
  return p?.place_kind === "city" || p?.place_type === "city";
}

function isDistrict(p) {
  if (!p || isCityLevel(p)) return false;
  return (
    p.place_type === "district" ||
    p.place_type === "city_part" ||
    p.place_kind === "district" ||
    p.place_kind === "city_part" ||
    // Legacy rows: parent link means this is a sub-region of a city
    p.parent_geoname_id != null ||
    (!!p.parent_label && p.place_kind !== "city")
  );
}

function jobProgressText(job) {
  const result = job?.result || {};
  if (result.message) return result.message;
  if (job?.status === "queued") {
    const ahead = Number(job.queue_ahead);
    if (Number.isFinite(ahead) && ahead > 0) {
      return ahead === 1
        ? "Waiting for 1 job…"
        : `Waiting for ${ahead} jobs…`;
    }
    return "Starting…";
  }
  return "Working…";
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
  if (!prepareJobId || preparePollInFlight) return;
  preparePollInFlight = true;
  const jobId = prepareJobId;
  try {
    const res = await WardAuth.apiFetch(`/api/jobs/${jobId}`);
    const job = await res.json().catch(() => ({}));
    if (!res.ok) return;
    // Stale poll after a newer prepare started
    if (prepareJobId !== jobId) return;
    const result = job.result || {};
    const progress = Math.max(0, Math.min(1, Number(job.progress) || 0));
    const pct = Math.round(progress * 100);
    document.getElementById("prepareFill").style.width = `${pct}%`;
    document.getElementById("preparePct").textContent = `${pct}%`;
    document.getElementById("prepareStatus").textContent = jobProgressText(job);
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
  } finally {
    preparePollInFlight = false;
  }
}

async function showAreaChoices(result) {
  const gen = ++areaChoicesGen;
  setMapLoading(false);
  prepareMeta = result;
  await refreshExistingLevels();
  // A newer prepare finished while we were refreshing — drop this paint
  if (gen !== areaChoicesGen) return;
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
    html += `<p class="area-choices-heading muted">Sub-regions</p>`;
    districts.forEach((d, i) => {
      html += areaChoiceHtml(d, (city ? 1 : 0) + i);
    });
  }
  box.innerHTML = html;
  box.hidden = false;
  document.getElementById("previewSub").textContent =
    "Pick the whole city or a sub-region - boundary shows on the map first";
  box.querySelectorAll("[data-area-i]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      selectAreaOption(Number(btn.dataset.areaI));
    });
  });
  // Pre-select first available (not already owned). Prefer leaving a user
  // pick alone if showAreaChoices races with itself.
  const firstFree = areaOptions.findIndex(
    (p) => p.osm_relation_id == null || !existingOsmIds.has(String(p.osm_relation_id))
  );
  if (firstFree >= 0) selectAreaOption(firstFree);
}

function areaChoiceHtml(p, i) {
  const kind = isDistrict(p) ? "Sub-region" : "Whole city";
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
  const seq = ++areaSelectSeq;
  // Deep-enough copy so later stale fetches cannot leak into areaOptions
  selectedPlace = {
    ...place,
    boundary: place.boundary || null,
    map_pack: place.map_pack ? { ...place.map_pack } : place.map_pack,
  };
  document.querySelectorAll(".area-choice-btn").forEach((btn) => {
    btn.classList.toggle("is-selected", Number(btn.dataset.areaI) === index);
  });
  setFixedLevelName(selectedPlace.label);
  document.getElementById("previewTitle").textContent = selectedPlace.label;
  document.getElementById("previewSub").textContent = isDistrict(selectedPlace)
    ? selectedPlace.boundary?.type
      ? `Sub-region boundary · ${fmtArea(selectedPlace.area_km2)}`
      : "Loading sub-region boundary..."
    : "Whole city";
  fillConfirm();
  setAreaNextEnabled(false);
  ensurePreviewMap();

  if (selectedPlace.boundary && selectedPlace.boundary.type) {
    selectedPlace.boundary_approximate = false;
    paintPreview(selectedPlace);
    document.getElementById("previewSub").textContent = isDistrict(selectedPlace)
      ? `Sub-region boundary · ${fmtArea(selectedPlace.area_km2)}`
      : `City boundary · ${fmtArea(selectedPlace.area_km2)}`;
    setAreaNextEnabled(true);
    return;
  }

  paintPreview(selectedPlace);
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
    // User picked another area while this request was in flight
    if (seq !== areaSelectSeq) return;
    if (bRes.ok && bData.boundary) {
      selectedPlace = {
        ...selectedPlace,
        boundary: bData.boundary,
        boundary_approximate: false,
        bbox: bData.bbox || selectedPlace.bbox,
      };
      document.getElementById("previewSub").textContent = isDistrict(selectedPlace)
        ? `Sub-region boundary · ${fmtArea(selectedPlace.area_km2)}`
        : `City boundary · ${fmtArea(selectedPlace.area_km2)}`;
      paintPreview(selectedPlace);
      setAreaNextEnabled(true);
    } else {
      document.getElementById("previewSub").textContent =
        bData.detail || "Could not load boundary";
      showToast(bData.detail || "Boundary missing", true);
    }
  } catch {
    if (seq !== areaSelectSeq) return;
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
  const name = label || "";
  const el = document.getElementById("levelName");
  if (el) el.value = name === "-" ? "" : name;
}

function fillConfirm() {
  if (!selectedPlace) return;
  const pack = selectedPlace.map_pack || prepareMeta?.map_pack || {};
  const area = selectedPlace.area_km2 != null ? ` · ${fmtArea(selectedPlace.area_km2)}` : "";
  document.getElementById("confirmPlace").textContent = `${selectedPlace.label}${area}`;
  const packId = pack.id || prepareMeta?.extract_id || "";
  const packName = pack.name || packId.split("/").pop() || "map pack";
  const size = pack.size_bytes != null ? fmtBytes(pack.size_bytes) : null;
  const usedBy = prepareMeta?.pack_levels_count;
  const bits = [packName];
  if (size) bits.push(size);
  if (usedBy != null) {
    bits.push(
      usedBy === 0
        ? "not used yet"
        : `shared with ${usedBy} region${usedBy === 1 ? "" : "s"}`
    );
  }
  document.getElementById("confirmSize").textContent = bits.join(" · ");
  document.getElementById("confirmTech").textContent = packId
    ? `Extract: ${packId}`
    : "Pack chosen automatically.";
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
  document.getElementById("progressMessage").textContent = jobProgressText(job);
  document.getElementById("progressEta").textContent = fmtEta(result.eta_seconds);
  if (result.stage) setStage(result.stage);

  if (job.status === "done") {
    clearInterval(pollTimer);
    pollTimer = null;
    document.getElementById("progressFill").style.width = "100%";
    const readyName = document.getElementById("levelName")?.value || selectedPlace?.label || "Region";
    document.getElementById("doneText").textContent = `${readyName} is ready.`;
    goStep("done");
    document.getElementById("stepDone").classList.add("celebrate");
    await loadLevels();
    return;
  }
  if (job.status === "error") {
    clearInterval(pollTimer);
    pollTimer = null;
    showToast(job.error || "Build failed", true);
    goStep(3);
  }
}

async function generateLevel() {
  if (!selectedPlace?.map_pack?.id) {
    showToast("Pick a place first", true);
    return;
  }
  const name = selectedPlace.label;
  setFixedLevelName(name);
  goStep(4);
  document.getElementById("progressTitle").textContent = `Building ${name}…`;
  document.getElementById("progressFill").style.width = "2%";
  setStage("extract");

  const payload = {
    name,
    place_query: selectedPlace.place_query || selectedPlace.label,
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
    goStep(3);
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

function levelCardHtml(lv, activeId, { nested = false, role = null } = {}) {
  const isActive = activeId && String(lv.id) === activeId;
  const title = lv.name || lv.place_query;
  const sub = role === "sub" || (nested && isDistrict(lv));
  const city = role === "city" || (!nested && isCityLevel(lv));
  const kind = sub
    ? `<em class="place-kind place-kind-sub">Sub-region</em>`
    : city
      ? `<em class="place-kind place-kind-city">Whole city</em>`
      : "";
  const pack = packLine(lv);
  const done = isLevelComplete(lv);
  const by = levelByProfile(lv);
  const tools = `<div class="tools-row tools-row-compact">
        <a class="btn btn-primary ${lv.status !== "ready" ? "is-disabled" : ""}" href="${
    lv.status === "ready" ? `/progress?level=${lv.id}` : "#"
  }" ${lv.status !== "ready" ? 'aria-disabled="true"' : ""}>Map</a>
        <button class="btn" data-load="${lv.id}" ${
    lv.status !== "ready" ? "disabled" : ""
  }>Use</button>
        <button class="btn" data-del="${lv.id}">Delete</button>
      </div>`;

  // Nested sub-regions: compact — modes + actions, no stat grid / under-hints
  if (sub) {
    return `
    <article class="level-card is-part is-minimal ${isActive ? "active" : ""} ${done ? "is-complete" : ""}">
      <header>
        <h3 class="level-card-title">
          <span class="level-card-name">${kind}${escapeHtml(title)}</span>
        </h3>
        <span class="level-status-stack">
          ${done ? `<span class="level-complete-badge" title="≥ ${COMPLETE_PCT}% Car roads unlocked">Complete</span>` : ""}
          <span class="level-status status-${lv.status}">${lv.status}</span>
        </span>
      </header>
      ${modeBarsHtml(by)}
      ${lv.error ? `<p class="error-text">${escapeHtml(lv.error)}</p>` : ""}
      ${tools}
    </article>`;
  }

  const placeHint =
    lv.place_query && lv.place_query !== title
      ? `<p class="muted level-place-hint">${escapeHtml(lv.place_query)}</p>`
      : "";
  return `
    <article class="level-card is-minimal ${isActive ? "active" : ""} ${done ? "is-complete" : ""}">
      <header>
        <h3 class="level-card-title">
          <span class="level-card-name">${kind}${escapeHtml(title)}</span>
        </h3>
        <span class="level-status-stack">
          ${done ? `<span class="level-complete-badge" title="≥ ${COMPLETE_PCT}% Car roads unlocked">Complete</span>` : ""}
          <span class="level-status status-${lv.status}">${lv.status}</span>
        </span>
      </header>
      ${placeHint}
      ${modeBarsHtml(by)}
      <p class="muted level-card-meta">${fmt(lv.road_km?.toFixed?.(1) ?? lv.road_km)} km${
    pack ? ` · ${pack}` : ""
  } · ${fmt(lv.networks_count)} nets</p>
      ${lv.error ? `<p class="error-text">${escapeHtml(lv.error)}</p>` : ""}
      ${tools}
    </article>`;
}

function groupSummaryBars(g) {
  if (g.city && g.city.status === "ready") return levelByProfile(g.city);
  return aggregateByProfile(g.parts);
}

function groupSubCounts(g, availableTotal) {
  const parts = (g.parts || []).filter((p) => p.status !== "error");
  const complete = parts.filter(
    (p) => p.status === "ready" && isLevelComplete(p)
  ).length;
  const progressing = Math.max(0, parts.length - complete);
  let unloaded = null;
  if (availableTotal != null && Number.isFinite(Number(availableTotal))) {
    // Catalog total minus anything already downloaded (complete or in progress).
    unloaded = Math.max(0, Number(availableTotal) - complete - progressing);
  }
  return { complete, progressing, unloaded, downloaded: parts.length };
}

const REGIONS_SORT_KEY = "wardrivrr_regions_sort_v2";
const REGIONS_SORT_OPTS = ["created", "completion", "name", "size"];

function readRegionsSort() {
  try {
    const v = localStorage.getItem(REGIONS_SORT_KEY);
    if (REGIONS_SORT_OPTS.includes(v)) return v;
  } catch {
    /* ignore */
  }
  return "created";
}

function writeRegionsSort(v) {
  try {
    localStorage.setItem(REGIONS_SORT_KEY, v);
  } catch {
    /* ignore */
  }
}

function bikeExploredPct(lv) {
  const row = levelByProfile(lv).bicycle;
  if (row && row.explored_pct != null) return Number(row.explored_pct) || 0;
  return 0;
}

function entryBikePct(entry) {
  if (entry.kind === "level") return bikeExploredPct(entry.level);
  const bars = groupSummaryBars(entry.group);
  return Number(bars.bicycle?.explored_pct) || 0;
}

function entryName(entry) {
  if (entry.kind === "level") {
    return String(entry.level.name || entry.level.place_query || "");
  }
  return String(entry.group.label || "");
}

function entryCreatedMs(entry) {
  const parse = (v) => {
    const t = Date.parse(v || "");
    return Number.isFinite(t) ? t : null;
  };
  if (entry.kind === "level") return parse(entry.level.created_at) || 0;
  const g = entry.group;
  const times = [];
  const c = parse(g.city?.created_at);
  if (c != null) times.push(c);
  for (const p of g.parts || []) {
    const t = parse(p.created_at);
    if (t != null) times.push(t);
  }
  // Earliest piece = when this region first appeared
  return times.length ? Math.min(...times) : 0;
}

function entryRoadKm(entry) {
  if (entry.kind === "level") return Number(entry.level.road_km) || 0;
  const g = entry.group;
  if (g.city && g.city.road_km != null) return Number(g.city.road_km) || 0;
  return (g.parts || []).reduce((s, p) => s + (Number(p.road_km) || 0), 0);
}

function sortRegionEntries(entries, sortBy) {
  const list = [...entries];
  list.sort((a, b) => {
    if (sortBy === "name") {
      return entryName(a).localeCompare(entryName(b), undefined, {
        sensitivity: "base",
      });
    }
    if (sortBy === "created") {
      return entryCreatedMs(b) - entryCreatedMs(a); // newest first
    }
    if (sortBy === "size") {
      return entryRoadKm(b) - entryRoadKm(a); // largest first
    }
    // completion (bike) — most complete first
    const d = entryBikePct(b) - entryBikePct(a);
    if (d !== 0) return d;
    return entryName(a).localeCompare(entryName(b), undefined, {
      sensitivity: "base",
    });
  });
  return list;
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
    else if (isPart && lv.parent_label) g.label = lv.parent_label;
  }

  // Root cities with districts → fold groups; lone cities / orphans → single cards.
  // One flat list (no "Other regions" bucket).
  const entries = [];
  for (const g of groups.values()) {
    g.parts.sort((a, b) =>
      String(a.name || a.place_query || "").localeCompare(
        String(b.name || b.place_query || "")
      )
    );
    if (g.parts.length) {
      entries.push({ kind: "group", group: g });
    } else if (g.city) {
      entries.push({ kind: "level", level: g.city });
    }
  }
  for (const lv of ungrouped) {
    entries.push({ kind: "level", level: lv });
  }
  return entries;
}

async function generateFromUnloaded(place) {
  if (!place?.map_pack?.id) {
    showToast("No map pack for this place", true);
    return;
  }
  const label = place.label || place.name || "Region";
  showToast(`Loading boundary for ${label}…`);
  let boundary = place.boundary;
  let bbox = place.bbox;
  try {
    const params = new URLSearchParams();
    if (place.osm_relation_id != null) {
      params.set("osm_relation_id", String(place.osm_relation_id));
    } else {
      params.set("lat", String(place.lat));
      params.set("lon", String(place.lon));
      if (place.name) params.set("name", place.name);
    }
    if (place.map_pack?.id) params.set("geofabrik_id", place.map_pack.id);
    const bRes = await WardAuth.apiFetch(`/api/levels/places/boundary?${params}`);
    const bBody = await bRes.json().catch(() => ({}));
    if (bRes.ok) {
      if (bBody.boundary) boundary = bBody.boundary;
      if (Array.isArray(bBody.bbox) && bBody.bbox.length >= 4) bbox = bBody.bbox;
    }
  } catch {
    /* fall through */
  }
  if (!boundary?.type) {
    showToast("Could not load boundary", true);
    return;
  }
  selectedPlace = {
    ...place,
    label,
    boundary,
    bbox: bbox || place.bbox,
    boundary_approximate: false,
  };
  setFixedLevelName(label);
  document.querySelector(".wizard-panel")?.scrollIntoView({
    behavior: "smooth",
    block: "start",
  });
  await generateLevel();
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
  el.querySelectorAll("[data-generate]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const key = btn.dataset.generate;
      const place = unloadedPlaceByKey.get(key);
      if (!place) return;
      btn.disabled = true;
      try {
        await generateFromUnloaded(place);
      } finally {
        btn.disabled = false;
      }
    });
  });
}

async function loadLevels() {
  const el = document.getElementById("levelsList");
  if (!el) return;
  try {
    const res = await WardAuth.apiFetch("/api/levels");
    const data = await res.json().catch(() => []);
    if (!res.ok) {
      el.textContent = data.detail || "Failed to load regions";
      return;
    }
    if (!Array.isArray(data) || !data.length) {
      el.innerHTML = `<p class="muted">No regions yet. Preload one above, or let Drive pick from your location.</p>`;
      return;
    }
    let activeId = null;
    try {
      const settings = await WardAuth.apiFetch("/api/settings").then((r) => r.json());
      activeId = settings.active_level_id ? String(settings.active_level_id) : null;
    } catch {
      /* list can render without active highlight */
    }
    const sortBy = readRegionsSort();
    const sortEl = document.getElementById("regionsSort");
    if (sortEl && sortEl.value !== sortBy) sortEl.value = sortBy;

    const entries = sortRegionEntries(groupLevels(data), sortBy);
    const menus = entries
      .filter((e) => e.kind === "group")
      .map((e) => e.group);

    const listHtml = entries
      .map((entry) => {
        if (entry.kind === "level") {
          const lv = entry.level;
          return levelCardHtml(lv, activeId, {
            role: isDistrict(lv) ? "sub" : isCityLevel(lv) ? "city" : null,
          });
        }
        const g = entry.group;
        const city = g.city;
        const counts = groupSubCounts(g, null);
        const cityDone = city && isLevelComplete(city);
        const partsAllDone =
          counts.downloaded > 0 &&
          counts.complete === counts.downloaded &&
          (counts.unloaded == null || counts.unloaded === 0);
        const groupDone = !!(cityDone || partsAllDone);
        const isActive =
          (city && activeId && String(city.id) === activeId) ||
          g.parts.some((p) => activeId && String(p.id) === activeId);
        const bars = groupSummaryBars(g);
        const pack = city ? packLine(city) : null;
        const cityReady = city?.status === "ready";
        const statusLabel = city?.status || "partial";
        const actions = city
          ? `<div class="tools-row tools-row-compact">
        <a class="btn btn-primary ${cityReady ? "" : "is-disabled"}" href="${
            cityReady ? `/progress?level=${city.id}` : "#"
          }" ${cityReady ? "" : 'aria-disabled="true"'}>Map</a>
        <button class="btn" data-load="${city.id}" ${cityReady ? "" : "disabled"}>Use</button>
        <button class="btn" data-del="${city.id}">Delete</button>
        <button type="button" class="btn level-group-fold" data-toggle-group aria-expanded="false">
          Sub-regions <span class="level-group-chevron" aria-hidden="true"></span>
        </button>
      </div>`
          : `<div class="tools-row tools-row-compact">
        <button type="button" class="btn level-group-fold" data-toggle-group aria-expanded="false">
          Sub-regions <span class="level-group-chevron" aria-hidden="true"></span>
        </button>
      </div>`;
        const metaBits = [];
        if (city) metaBits.push(`${fmt(city.road_km?.toFixed?.(1) ?? city.road_km)} km`);
        if (pack) metaBits.push(pack);
        if (city) metaBits.push(`${fmt(city.networks_count)} nets`);
        return `
      <section class="level-group ${isActive ? "has-active" : ""} ${groupDone ? "is-complete" : ""}" data-group-key="${escapeHtml(g.key)}">
        <article class="level-card level-group-root is-minimal ${city && activeId && String(city.id) === activeId ? "active" : ""} ${cityDone ? "is-complete" : ""}">
          <header>
            <h3 class="level-card-title">
              <span class="level-card-name"><em class="place-kind place-kind-city">City</em>${escapeHtml(g.label)}</span>
            </h3>
            <span class="level-status-stack">
              ${groupDone ? `<span class="level-complete-badge" title="≥ ${COMPLETE_PCT}% Car roads unlocked">Complete</span>` : ""}
              <span class="level-status status-${statusLabel}">${statusLabel}</span>
            </span>
          </header>
          ${
            city
              ? ""
              : `<p class="muted level-group-note">City pack not loaded — sub-regions only</p>`
          }
          <div class="level-group-summary-tally" data-sub-tally>
            ${subTallyHtml(counts.complete, counts.progressing, counts.unloaded)}
          </div>
          ${modeBarsHtml(bars)}
          ${metaBits.length ? `<p class="muted level-card-meta">${metaBits.join(" · ")}</p>` : ""}
          ${city?.error ? `<p class="error-text">${escapeHtml(city.error)}</p>` : ""}
          ${actions}
        </article>
        <div class="level-group-body" data-group-body>
          ${g.parts.map((p) => levelCardHtml(p, activeId, { nested: true, role: "sub" })).join("")}
        </div>
      </section>`;
      })
      .join("");

    el.innerHTML = listHtml;
    bindLevelActions(el);
    fillGroupAvailableCounts(el, menus);
  } catch (err) {
    el.textContent = `Could not load regions: ${err?.message || err}`;
  }
}

async function fillGroupAvailableCounts(el, menus) {
  if (!el || !menus?.length) return;
  await Promise.all(
    menus.map(async (g) => {
      const section = el.querySelector(
        `[data-group-key="${CSS.escape(g.key)}"]`
      );
      const tallyHost = section?.querySelector("[data-sub-tally]");
      const bodyEl = section?.querySelector("[data-group-body]");
      if (!tallyHost) return;
      const anchor = g.city || g.parts[0];
      const center = levelCenter(anchor);
      if (!center) return;
      const params = new URLSearchParams({
        lat: String(center.lat),
        lon: String(center.lon),
      });
      if (g.label) params.set("name", g.label);
      const gn = g.city?.geoname_id ?? g.parts[0]?.parent_geoname_id;
      if (gn != null) params.set("geoname_id", String(gn));
      if (g.city?.geofabrik_id) params.set("geofabrik_id", g.city.geofabrik_id);
      else if (g.parts[0]?.geofabrik_id) params.set("geofabrik_id", g.parts[0].geofabrik_id);
      // Only pass the city root bbox. A lone sub-region's bbox is too small for
      // the parts size heuristic and would report 0 unloaded (e.g. Köln Innenstadt).
      const cityBbox = Array.isArray(g.city?.bbox) ? g.city.bbox : null;
      if (cityBbox && cityBbox.length >= 4) {
        params.set("bbox", cityBbox.slice(0, 4).join(","));
      }
      try {
        const res = await WardAuth.apiFetch(`/api/levels/places/parts?${params}`);
        const body = await res.json().catch(() => ({}));
        if (!res.ok) return;
        const catalogParts = Array.isArray(body?.parts) ? body.parts : null;
        if (catalogParts == null) return;
        const catalog = catalogParts.length;
        const downloaded = g.parts.filter((p) => p.status !== "error").length;
        const available = Math.max(catalog, downloaded);
        const counts = groupSubCounts(g, available);
        tallyHost.innerHTML = subTallyHtml(
          counts.complete,
          counts.progressing,
          counts.unloaded
        );

        if (!bodyEl) return;
        // Drop previous unloaded rows, keep loaded cards
        bodyEl.querySelectorAll(".is-unloaded").forEach((n) => n.remove());
        const missing = unloadedPartsForGroup(g, catalogParts).sort((a, b) =>
          String(a.label || a.name || "").localeCompare(
            String(b.label || b.name || "")
          )
        );
        if (!missing.length) return;
        const frag = document.createDocumentFragment();
        const wrap = document.createElement("div");
        wrap.innerHTML = missing
          .map((p, i) => unloadedRowHtml(p, `${g.key}-u${i}`))
          .join("");
        while (wrap.firstChild) frag.appendChild(wrap.firstChild);
        bodyEl.appendChild(frag);
        bodyEl.querySelectorAll("[data-generate]").forEach((btn) => {
          if (btn.dataset.bound === "1") return;
          btn.dataset.bound = "1";
          btn.addEventListener("click", async () => {
            const place = unloadedPlaceByKey.get(btn.dataset.generate);
            if (!place) return;
            btn.disabled = true;
            try {
              await generateFromUnloaded(place);
            } finally {
              btn.disabled = false;
            }
          });
        });
      } catch {
        /* keep downloaded-only tally */
      }
    })
  );
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
      showToast("Wait for the boundary to load", true);
      return;
    }
    if (Number(btn.dataset.next) === 3) fillConfirm();
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

const regionsSortEl = document.getElementById("regionsSort");
if (regionsSortEl) {
  regionsSortEl.value = readRegionsSort();
  regionsSortEl.addEventListener("change", () => {
    const v = regionsSortEl.value;
    writeRegionsSort(REGIONS_SORT_OPTS.includes(v) ? v : "created");
    loadLevels();
  });
}
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
  await loadLevels();
})();
