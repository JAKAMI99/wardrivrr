const els = {
  wifi: document.getElementById("statWifi"),
  bt: document.getElementById("statBt"),
  ble: document.getElementById("statBle"),
  samples: document.getElementById("statSamples"),
  samplesHint: document.getElementById("statSamplesHint"),
  toast: document.getElementById("toast"),
};

function fmt(n) {
  if (n == null || Number.isNaN(n)) return "-";
  return new Intl.NumberFormat().format(n);
}

function showToast(message, isError = false) {
  els.toast.hidden = false;
  els.toast.textContent = message;
  els.toast.classList.toggle("error", isError);
}

function setChip(id, kind, label) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("ok", "warn", "down", "na");
  if (kind) el.classList.add(kind);
  el.innerHTML = `<span class="dot"></span>${label}`;
}

function chipFromState(service, labels) {
  const state = service?.state;
  if (state === "na" || service?.expected === false) {
    return { kind: "na", label: labels.na };
  }
  if (state === "ok") return { kind: "ok", label: labels.ok(service) };
  if (state === "warn") return { kind: "warn", label: labels.warn(service) };
  return { kind: "down", label: labels.down(service) };
}

function renderXp(prog) {
  const strip = document.getElementById("xpStrip");
  if (!strip || !prog) return;
  strip.hidden = false;
  const lvl = document.getElementById("xpLevel");
  const pts = document.getElementById("xpPoints");
  const next = document.getElementById("xpNext");
  const fill = document.getElementById("xpBarFill");
  if (lvl) lvl.textContent = `Level ${prog.level}`;
  if (pts) pts.textContent = `${fmt(prog.xp)} XP`;
  if (next) next.textContent = `${fmt(prog.xp_to_next)} XP to next`;
  if (fill) fill.style.width = `${Math.min(100, Number(prog.progress_pct) || 0)}%`;
}

async function loadOverview() {
  try {
    const [healthRes, statsRes, systemRes, xpRes] = await Promise.all([
      WardAuth.apiFetch("/api/health"),
      WardAuth.apiFetch("/api/stats"),
      WardAuth.apiFetch("/api/system/status"),
      WardAuth.apiFetch("/api/me/progress"),
    ]);
    const health = await healthRes.json().catch(() => ({}));
    const stats = await statsRes.json().catch(() => ({}));
    const system = await systemRes.json().catch(() => ({}));
    if (xpRes.ok) renderXp(await xpRes.json().catch(() => null));

    if (!healthRes.ok) {
      setChip("chipDb", "down", "Database down");
      showToast("Database unreachable - start PostGIS and reload.", true);
      return;
    }

    const summary = stats.summary || {};
    els.wifi.textContent = fmt(summary.networks_wifi ?? system.database?.networks_wifi);
    els.bt.textContent = fmt(summary.networks_bt ?? system.database?.networks_bt);
    els.ble.textContent = fmt(summary.networks_ble ?? system.database?.networks_ble);
    els.samples.textContent = fmt(health.samples ?? summary.samples);
    const total = summary.networks ?? health.networks;
    if (total != null) {
      els.samplesHint.textContent = `${fmt(total)} networks total`;
    }

    const dbChip = chipFromState(system.database, {
      na: "Database N/A",
      ok: (s) => (s.size_human ? `DB ${s.size_human}` : "Database OK"),
      warn: () => "Database warn",
      down: () => "Database down",
    });
    setChip("chipDb", dbChip.kind, dbChip.label);

    const gpsChip = chipFromState(system.gps, {
      na: "GPS N/A",
      ok: (s) => `GPS ${Number(s.lat).toFixed(4)}, ${Number(s.lon).toFixed(4)}`,
      warn: () => "GPS no fix",
      down: () => "GPS offline",
    });
    setChip("chipGps", gpsChip.kind, gpsChip.label);

    const kismetChip = chipFromState(system.kismet, {
      na: "Kismet N/A",
      ok: () => "Kismet running",
      warn: () => "Kismet stopped",
      down: () => "Kismet missing",
    });
    setChip("chipKismet", kismetChip.kind, kismetChip.label);

    const routingChip = chipFromState(system.valhalla, {
      na: "Routing N/A",
      ok: () => "Routing running",
      warn: () => "Routing stopped",
      down: () => "Routing missing",
    });
    setChip("chipRouting", routingChip.kind, routingChip.label);
  } catch {
    showToast("API unreachable - is the backend running?", true);
  }
}

(async () => {
  await WardAuth.requireAuth();
  loadOverview();
})();
