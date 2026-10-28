const statusUpdated = document.getElementById("statusUpdated");
const deployModeLabel = document.getElementById("deployModeLabel");

function fmt(n) {
  if (n == null || Number.isNaN(Number(n))) return "-";
  return new Intl.NumberFormat().format(n);
}

function fmtCoord(n, digits = 5) {
  if (n == null || Number.isNaN(Number(n))) return "-";
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

/** Client-facing Kismet Web UI (same host as this page, port from API url or 2501). */
function kismetWebuiHref(info) {
  let port = 2501;
  const raw = info?.url || info?.webui_url;
  if (raw) {
    try {
      const u = new URL(raw, window.location.origin);
      if (u.port) port = Number(u.port) || port;
      else if (u.protocol === "https:") port = 443;
      else if (u.protocol === "http:") port = 80;
    } catch (_) {
      /* keep default */
    }
  }
  const host = window.location.hostname || "127.0.0.1";
  return `http://${host}:${port}/`;
}

function paintKismetWebui(info) {
  const btn = document.getElementById("kismetWebui");
  if (!btn) return;
  const show =
    info &&
    info.expected !== false &&
    info.state !== "na";
  btn.hidden = !show;
  if (!show) return;
  btn.href = kismetWebuiHref(info);
  const up = !!(info.http_ok || info.state === "ok" || info.running);
  btn.classList.toggle("is-down", !up);
  btn.setAttribute("aria-disabled", up ? "false" : "true");
  btn.title = up ? "Open Kismet Web UI" : "Kismet is down";
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
    fillDl(meta, [
      ["Host", `${gps?.host}:${gps?.port}`],
      ["Device", gps?.device],
      ["Device present", gps?.device_present == null ? null : String(gps.device_present)],
    ]);
    return;
  }
  if (gps.fix) {
    setBadge(badge, "live", "Fix");
    title.textContent = "GPS fix";
    detail.textContent = `Mode ${gps.mode} · ${fmtCoord(gps.lat)}, ${fmtCoord(gps.lon)}`;
  } else if (gps.device_present === false) {
    setBadge(badge, "warn", "No dongle");
    title.textContent = "GPS waiting";
    detail.textContent =
      gps.detail || `Plug in receiver (${gps.device || "/dev/ttyACM0"})`;
  } else {
    setBadge(badge, "warn", "No fix");
    title.textContent = "GPS listening";
    detail.textContent =
      gps.detail || "gpsd up - waiting for satellites";
  }
  fillDl(meta, [
    ["Host", `${gps?.host}:${gps?.port}`],
    ["Device", gps?.device],
    ["Device present", gps?.device_present == null ? null : String(gps.device_present)],
    [
      "USB GPS nodes",
      Array.isArray(gps?.usb_gps_nodes) && gps.usb_gps_nodes.length
        ? gps.usb_gps_nodes.join(", ")
        : "none",
    ],
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
  // Prefer API state (HTTP probes) - API container has no Docker CLI
  if (info?.state === "ok" || info?.http_ok || info?.running) {
    setBadge(badge, "live", "OK");
    title.textContent = info.name || fallbackTitle;
    detail.textContent =
      info.detail ||
      (info.health ? `Healthy · ${info.health}` : "Reachable");
  } else if (
    info?.state === "warn" ||
    info?.status === "waiting for map" ||
    info?.status === "waiting for seed" ||
    info?.status === "building tiles" ||
    info?.status === "not started"
  ) {
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
  const rows = [
    ["URL", info.url],
    ["Name", info.name],
    ["Status", info.status],
    ["Image", info.image],
    ["Health", info.health],
    ["PBF ready", info.pbf_ready == null ? null : String(info.pbf_ready)],
  ];
  if (prefix === "kismet" || info.wifi || info.bluetooth) {
    const wifi = info.wifi || {};
    const bt = info.bluetooth || {};
    let wifiLabel = null;
    if (wifi.present && (wifi.interface || wifi.name)) {
      wifiLabel = wifi.interface || wifi.name;
    } else if (wifi.present === false) {
      wifiLabel = "none";
    }
    let btLabel = null;
    if (bt.present === true) {
      btLabel = bt.interface ? `yes · ${bt.interface}` : "yes";
    } else if (bt.present === false) {
      btLabel = "no";
    }
    rows.push(["Wi-Fi", wifiLabel], ["Bluetooth", btLabel]);
  }
  if (info.map_label) {
    rows.push(["Map", info.map_label]);
  }
  fillDl(meta, rows);
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
    ["Wi-Fi", fmt(db.networks_wifi)],
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
  const kismetH = storage?.kismet_logs_human || "0 B";
  const uploadsH = storage?.uploads_human || storage?.raw_incoming_human || "0 B";
  document.getElementById("storageDetail").textContent =
    `Kismet logs ${kismetH} · Uploads ${uploadsH} · DB ${db?.size_human || "-"}`;
  // No filesystem path shown — TTS mangled "incoming" and live capture
  // never lands in the upload queue anyway.
  fillDl(document.getElementById("storageMeta"), [
    ["Kismet logs", `${kismetH} · ${fmt(storage?.kismet_logs_files)} files`],
    [
      "Upload queue",
      `${uploadsH} · ${fmt(storage?.uploads_files ?? storage?.raw_incoming_files)} files`,
    ],
    ["Database size", db?.size_human],
    ["Disk free", storage?.disk_free_human],
    ["Disk used", `${storage?.disk_used_human} / ${storage?.disk_total_human}`],
  ]);
}

function setMeter(fillId, meterId, pctElId, pct) {
  const fill = document.getElementById(fillId);
  const meter = document.getElementById(meterId);
  const label = document.getElementById(pctElId);
  const n = pct == null || Number.isNaN(Number(pct)) ? null : Math.max(0, Math.min(100, Number(pct)));
  if (label) label.textContent = n == null ? "—" : `${n.toFixed(0)}%`;
  if (fill) fill.style.width = n == null ? "0%" : `${n}%`;
  if (meter) {
    if (n == null) meter.removeAttribute("aria-valuenow");
    else meter.setAttribute("aria-valuenow", String(Math.round(n)));
  }
  if (fill) {
    fill.classList.toggle("is-hot", n != null && n >= 85);
    fill.classList.toggle("is-warm", n != null && n >= 65 && n < 85);
  }
}

function paintHost(host) {
  const badge = document.getElementById("hostBadge");
  const title = document.getElementById("hostTitle");
  const detail = document.getElementById("hostDetail");
  if (!host || host.ok === false) {
    setBadge(badge, "warn", "Limited");
    title.textContent = "Host";
    detail.textContent = host?.detail || "Host metrics unavailable";
    setMeter("hostCpuFill", "hostCpuMeter", "hostCpuPct", null);
    setMeter("hostRamFill", "hostRamMeter", "hostRamPct", null);
    fillDl(document.getElementById("hostMeta"), []);
    return;
  }
  const cpu = host.cpu || {};
  const mem = host.memory || {};
  const disk = host.disk || {};
  setBadge(badge, "live", "OK");
  title.textContent = host.hostname || "Host";
  const ghz = cpu.freq_ghz != null ? `${cpu.freq_ghz} GHz` : null;
  const cores =
    cpu.cores != null || cpu.threads != null
      ? `${cpu.cores ?? "?"} cores / ${cpu.threads ?? "?"} threads`
      : null;
  detail.textContent = [cpu.model, ghz, cores].filter(Boolean).join(" · ") || host.os || "Machine";

  setMeter("hostCpuFill", "hostCpuMeter", "hostCpuPct", cpu.percent);
  setMeter("hostRamFill", "hostRamMeter", "hostRamPct", mem.percent);

  fillDl(document.getElementById("hostMeta"), [
    ["CPU", cpu.model],
    ["Clock", ghz],
    ["Cores / threads", cores],
    [
      "RAM",
      mem.used_human && mem.total_human
        ? `${mem.used_human} / ${mem.total_human}`
        : null,
    ],
    [
      "Disk",
      disk.used_human && disk.total_human
        ? `${disk.used_human} / ${disk.total_human} (${disk.percent ?? "—"}%)`
        : null,
    ],
    ["Temperature", host.temperature_c != null ? `${host.temperature_c} °C` : null],
    ["LAN IP", host.lan_ip],
    ["Wi‑Fi SSID", host.wifi_ssid],
    ["OS", host.os],
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
  paintKismetWebui(data.kismet);
  paintContainer("valhalla", data.valhalla, "Valhalla");
  paintDb(data.database, data.postgis_container);
  paintStorage(data.storage, data.database);
  paintHost(data.host);

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
