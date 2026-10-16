const statusUpdated = document.getElementById("statusUpdated");
const deployModeLabel = document.getElementById("deployModeLabel");

function fmt(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return new Intl.NumberFormat().format(n);
}

function fmtCoord(n, digits = 5) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return Number(n).toFixed(digits);
}

function setBadge(el, kind, text) {
  el.textContent = text;
  el.classList.remove("live", "warn", "down", "na");
  if (kind) el.classList.add(kind);
}

function fillDl(el, rows) {
  el.innerHTML = rows
    .filter(([, v]) => v != null && v !== "")
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
    .join("");
}

function paintNa(badge, titleEl, detailEl, metaEl, title, detail) {
  setBadge(badge, "na", "N/A");
  titleEl.textContent = title;
  detailEl.textContent = detail || "Not used in this deployment mode";
  fillDl(metaEl, []);
}

function paintGps(gps) {
  const badge = document.getElementById("gpsBadge");
  const title = document.getElementById("gpsTitle");
  const detail = document.getElementById("gpsDetail");
  const meta = document.getElementById("gpsMeta");
  if (gps?.state === "na" || gps?.expected === false) {
    paintNa(badge, title, detail, meta, "GPS", gps?.detail);
    return;
  }
  if (!gps?.reachable) {
    setBadge(badge, "down", "Offline");
    title.textContent = "GPS";
    detail.textContent = gps?.detail || `gpsd not reachable at ${gps?.host}:${gps?.port}`;
    fillDl(meta, [["Host", `${gps?.host}:${gps?.port}`]]);
    return;
  }
  if (gps.fix) {
    setBadge(badge, "live", "Fix");
    title.textContent = "GPS fix";
    detail.textContent = `Mode ${gps.mode} · ${fmtCoord(gps.lat)}, ${fmtCoord(gps.lon)}`;
  } else {
    setBadge(badge, "warn", "No fix");
    title.textContent = "GPS listening";
    detail.textContent = gps.detail || "gpsd up, waiting for a fix";
  }
  fillDl(meta, [
    ["Latitude", fmtCoord(gps.lat)],
    ["Longitude", fmtCoord(gps.lon)],
    ["Altitude", gps.alt != null ? `${Number(gps.alt).toFixed(1)} m` : null],
    ["Speed", gps.speed != null ? `${Number(gps.speed).toFixed(1)} m/s` : null],
    [
      "Satellites",
      gps.satellites_used != null ? `${gps.satellites_used} used / ${gps.satellites}` : gps.satellites,
    ],
    ["Time", gps.time],
  ]);
}

function paintContainer(prefix, info, fallbackTitle) {
  const badge = document.getElementById(`${prefix}Badge`);
  const title = document.getElementById(`${prefix}Title`);
  const detail = document.getElementById(`${prefix}Detail`);
  const meta = document.getElementById(`${prefix}Meta`);
  if (info?.state === "na" || info?.expected === false) {
    paintNa(badge, title, detail, meta, fallbackTitle, info?.detail);
    return;
  }
  // Prefer API state (HTTP probes) — API container has no Docker CLI
  if (info?.state === "ok" || info?.http_ok || info?.running) {
    setBadge(badge, "live", "OK");
    title.textContent = info.name || fallbackTitle;
    detail.textContent =
      info.detail ||
      (info.health ? `Healthy · ${info.health}` : "Reachable");
  } else if (info?.state === "warn" || info?.status === "waiting for map") {
    setBadge(badge, "warn", "Waiting");
    title.textContent = fallbackTitle;
    detail.textContent = info.detail || info.status || "Not ready yet";
  } else if (!info?.found && !info?.http_ok) {
    setBadge(badge, "down", "Down");
    title.textContent = fallbackTitle;
    detail.textContent = info?.detail || "Not reachable";
  } else {
    setBadge(badge, "warn", "Stopped");
    title.textContent = info.name || fallbackTitle;
    detail.textContent = info.detail || `Status: ${info.status}`;
  }
  fillDl(meta, [
    ["URL", info.url],
    ["Name", info.name],
    ["Status", info.status],
    ["Image", info.image],
    ["Health", info.health],
    ["PBF ready", info.pbf_ready == null ? null : String(info.pbf_ready)],
  ]);
}

function paintDb(db, postgisContainer) {
  const badge = document.getElementById("dbBadge");
  const title = document.getElementById("dbTitle");
  const detail = document.getElementById("dbDetail");
  if (!db?.ok) {
    setBadge(badge, "down", "Down");
    title.textContent = "Database";
    detail.textContent = db?.detail || "Cannot connect";
    fillDl(document.getElementById("dbMeta"), [
      ["Host", `${db?.host}:${db?.port}`],
      ["DB", db?.dbname],
    ]);
    return;
  }
  setBadge(badge, "live", "OK");
  title.textContent = db.dbname || "wardriving";
  detail.textContent = db.postgis ? `PostGIS ${String(db.postgis).split(" ")[0]}` : "Connected";
  fillDl(document.getElementById("dbMeta"), [
    ["Host", `${db.host}:${db.port}`],
    ["Size", db.size_human],
    ["Networks", fmt(db.networks)],
    ["Wi‑Fi", fmt(db.networks_wifi)],
    ["BT", fmt(db.networks_bt)],
    ["BLE", fmt(db.networks_ble)],
    ["Samples", fmt(db.samples)],
    [
      "Container",
      postgisContainer?.found
        ? `${postgisContainer.name} · ${postgisContainer.status}`
        : "n/a",
    ],
    ["First seen", db.first_seen],
    ["Last seen", db.last_seen],
  ]);
}

function paintStorage(storage, db) {
  const badge = document.getElementById("storageBadge");
  setBadge(badge, "live", "OK");
  document.getElementById("storageTitle").textContent = "Storage";
  document.getElementById("storageDetail").textContent =
    `Raw files ${storage?.raw_incoming_human || "0 B"} · DB ${db?.size_human || "—"}`;
  fillDl(document.getElementById("storageMeta"), [
    ["Raw path", storage?.raw_incoming_path],
    ["Raw size", storage?.raw_incoming_human],
    ["Raw files", fmt(storage?.raw_incoming_files)],
    ["Database size", db?.size_human],
    ["Disk free", storage?.disk_free_human],
    ["Disk used", `${storage?.disk_used_human} / ${storage?.disk_total_human}`],
  ]);
}

async function loadStatus() {
  const res = await WardAuth.apiFetch("/api/system/status");
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "status failed");

  const mode = data.deployment?.mode || "full";
  deployModeLabel.textContent =
    mode === "database"
      ? "Mode: database (GPS / Kismet / routing N/A)"
      : "Mode: full (capture & routing expected)";

  paintGps(data.gps);
  paintContainer("kismet", data.kismet, "Kismet");
  paintContainer("valhalla", data.valhalla, "Valhalla");
  paintDb(data.database, data.postgis_container);
  paintStorage(data.storage, data.database);

  document.getElementById("statNetworks").textContent = fmt(data.database?.networks);
  document.getElementById("statWifi").textContent = fmt(data.database?.networks_wifi);
  document.getElementById("statBt").textContent = fmt(data.database?.networks_bt);
  document.getElementById("statBle").textContent = fmt(data.database?.networks_ble);
  document.getElementById("statSamples").textContent = fmt(data.database?.samples);
  document.getElementById("statKismetSamples").textContent = fmt(data.database?.samples_kismet);
  document.getElementById("statWigleSamples").textContent = fmt(data.database?.samples_wigle);
  statusUpdated.textContent = new Date().toLocaleTimeString();
}

document.getElementById("refreshStatus").addEventListener("click", () => {
  loadStatus().catch((err) => {
    statusUpdated.textContent = String(err);
  });
});

(async () => {
  await WardAuth.requireAuth();
  loadStatus().catch((err) => {
    statusUpdated.textContent = String(err);
  });
  setInterval(() => {
    loadStatus().catch(() => {});
  }, 5000);
})();
