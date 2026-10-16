let dashboard = null;
let period = "today";

const fmt = (n) =>
  n == null || Number.isNaN(Number(n)) ? "—" : new Intl.NumberFormat().format(n);

function setPeriod(next) {
  period = next;
  document.querySelectorAll(".period-tab").forEach((btn) => {
    const on = btn.dataset.period === period;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  paintPeriod();
}

function paintPeriod() {
  if (!dashboard) return;
  const block = dashboard[period] || dashboard.today;
  document.getElementById("pNetworks").textContent = fmt(block.networks);
  document.getElementById("pWifi").textContent = fmt(block.wifi);
  document.getElementById("pBt").textContent = fmt(block.bt);
  document.getElementById("pBle").textContent = fmt(block.ble);
  document.getElementById("pSamples").textContent = fmt(block.samples);
  const hints = {
    today: "first seen today",
    week: "first seen in last 7 days",
    all_time: "all discovered networks",
  };
  document.getElementById("pNetworksHint").textContent = hints[period] || "";
}

function paintMeters() {
  const wifi = dashboard.milestones.wifi;
  const nets = dashboard.milestones.networks;
  document.getElementById("mileWifiFill").style.width = `${Math.round(wifi.progress * 100)}%`;
  document.getElementById("mileNetFill").style.width = `${Math.round(nets.progress * 100)}%`;
  document.getElementById("mileWifiLabel").textContent =
    `${fmt(wifi.current)} Wi‑Fi · ${fmt(wifi.remaining)} to ${fmt(wifi.next)}`;
  document.getElementById("mileNetLabel").textContent =
    `${fmt(nets.current)} total · ${fmt(nets.remaining)} to ${fmt(nets.next)}`;
  document.getElementById("mileWifiCaption").textContent =
    wifi.remaining === 0 ? "Milestone cleared — next rung unlocked" : "Goal gradient: closer = more pull";
  document.getElementById("mileNetCaption").textContent = "Collection competence across all radios";
}

function paintStreak() {
  const s = dashboard.streak;
  document.getElementById("streakCurrent").textContent = fmt(s.current);
  document.getElementById("streakBest").textContent = `${fmt(s.best)} days`;
  const badge = document.getElementById("streakBadge");
  badge.classList.remove("live", "warn", "na");
  if (s.active_today) {
    badge.textContent = "On fire";
    badge.classList.add("live");
    document.getElementById("streakToday").textContent = "Active — you logged finds today";
    document.getElementById("streakCopy").textContent =
      "Consecutive days with ≥1 new network. Competence compounds.";
  } else if (s.grace) {
    badge.textContent = "Grace";
    badge.classList.add("warn");
    document.getElementById("streakToday").textContent = "Quiet so far — streak still recoverable today";
    document.getElementById("streakCopy").textContent =
      "Optional continuity, not a punishment. One find keeps the chain.";
  } else {
    badge.textContent = "Ready";
    badge.classList.add("na");
    document.getElementById("streakToday").textContent = "No streak yet — start with one network";
    document.getElementById("streakCopy").textContent =
      "Streaks support habit without replacing curiosity.";
  }
}

function paintBest() {
  const pb = dashboard.personal_best;
  const y = dashboard.yesterday;
  const t = dashboard.today;
  document.getElementById("bestDayCount").textContent = fmt(pb.best_day_networks);
  document.getElementById("bestDayTitle").textContent = pb.best_day
    ? `Best day · ${pb.best_day}`
    : "Best day";
  document.getElementById("bestDayCopy").textContent =
    pb.best_day_networks > 0
      ? "Your peak single-day haul — beat it when you want"
      : "Your peak day appears after the first discoveries";

  const delta = t.networks - y.networks;
  if (y.networks === 0 && t.networks === 0) {
    document.getElementById("vsYesterday").textContent = "Even · both quiet";
  } else if (delta > 0) {
    document.getElementById("vsYesterday").textContent = `+${fmt(delta)} vs yesterday`;
  } else if (delta < 0) {
    document.getElementById("vsYesterday").textContent =
      `${fmt(t.networks)} today · ${fmt(y.networks)} yesterday`;
  } else {
    document.getElementById("vsYesterday").textContent = `Tied with yesterday (${fmt(t.networks)})`;
  }

  const first = dashboard.span?.first_seen;
  document.getElementById("spanFirst").textContent = first
    ? new Date(first).toLocaleDateString()
    : "—";
}

function paintHero() {
  const m = dashboard.motivation;
  document.getElementById("statsHeadline").textContent = m.headline;
  document.getElementById("statsNudge").textContent = m.nudge;
  document.getElementById("statsTz").textContent =
    `Explorer clock · ${dashboard.timezone}`;
}

async function load() {
  const res = await WardAuth.apiFetch("/api/stats/dashboard");
  if (!res.ok) {
    document.getElementById("statsHeadline").textContent = "Stats offline";
    document.getElementById("statsNudge").textContent = await res.text();
    return;
  }
  dashboard = await res.json();
  paintHero();
  paintPeriod();
  paintMeters();
  paintStreak();
  paintBest();
}

document.querySelectorAll(".period-tab").forEach((btn) => {
  btn.addEventListener("click", () => setPeriod(btn.dataset.period));
});

(async () => {
  await WardAuth.requireAuth();
  load();
})();
