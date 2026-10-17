let dashboard = null;
let progress = null;
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
  if (!dashboard?.milestones) return;
  const wifi = dashboard.milestones.wifi;
  const nets = dashboard.milestones.networks;
  document.getElementById("mileWifiFill").style.width = `${Math.round(wifi.progress * 100)}%`;
  document.getElementById("mileNetFill").style.width = `${Math.round(nets.progress * 100)}%`;
  document.getElementById("mileWifiLabel").textContent =
    `${fmt(wifi.current)} Wi‑Fi · ${fmt(wifi.remaining)} to ${fmt(wifi.next)}`;
  document.getElementById("mileNetLabel").textContent =
    `${fmt(nets.current)} total · ${fmt(nets.remaining)} to ${fmt(nets.next)}`;
  document.getElementById("mileWifiCaption").textContent =
    wifi.remaining === 0 ? "Milestone cleared" : "Closer = more pull";
  document.getElementById("mileNetCaption").textContent = "Across all radios";
}

function paintStreak() {
  if (!dashboard?.streak) return;
  const s = dashboard.streak;
  document.getElementById("streakCurrent").textContent = fmt(s.current);
  document.getElementById("streakBest").textContent = `${fmt(s.best)} days`;
  const badge = document.getElementById("streakBadge");
  badge.classList.remove("live", "warn", "na");
  if (s.active_today) {
    badge.textContent = "On fire";
    badge.classList.add("live");
    document.getElementById("streakToday").textContent = "Active — finds today";
    document.getElementById("streakCopy").textContent =
      "Consecutive days with ≥1 new network.";
  } else if (s.grace) {
    badge.textContent = "Grace";
    badge.classList.add("warn");
    document.getElementById("streakToday").textContent = "Quiet — still recoverable today";
    document.getElementById("streakCopy").textContent =
      "One find keeps the chain.";
  } else {
    badge.textContent = "Ready";
    badge.classList.add("na");
    document.getElementById("streakToday").textContent = "No streak yet";
    document.getElementById("streakCopy").textContent =
      "Start with one network.";
  }
}

function paintBest() {
  if (!dashboard) return;
  const pb = dashboard.personal_best;
  const y = dashboard.yesterday;
  const t = dashboard.today;
  document.getElementById("bestDayCount").textContent = fmt(pb.best_day_networks);
  document.getElementById("bestDayTitle").textContent = pb.best_day
    ? `Best day · ${pb.best_day}`
    : "Best day";
  document.getElementById("bestDayCopy").textContent =
    pb.best_day_networks > 0
      ? "Peak single-day haul"
      : "Appears after first discoveries";

  const delta = t.networks - y.networks;
  if (y.networks === 0 && t.networks === 0) {
    document.getElementById("vsYesterday").textContent = "Even · both quiet";
  } else if (delta > 0) {
    document.getElementById("vsYesterday").textContent = `+${fmt(delta)} vs yesterday`;
  } else if (delta < 0) {
    document.getElementById("vsYesterday").textContent =
      `${fmt(t.networks)} today · ${fmt(y.networks)} yesterday`;
  } else {
    document.getElementById("vsYesterday").textContent = `Tied (${fmt(t.networks)})`;
  }

  const first = dashboard.span?.first_seen;
  document.getElementById("spanFirst").textContent = first
    ? new Date(first).toLocaleDateString()
    : "—";
}

function paintExplorerHero() {
  if (!progress) return;
  const level = progress.level ?? "—";
  const xp = progress.xp ?? 0;
  const toNext = progress.xp_to_next ?? 0;
  const pct = Math.min(100, Number(progress.progress_pct) || 0);

  document.getElementById("explorerLevel").textContent = level;
  document.getElementById("statsHeadline").textContent = `Level ${level}`;
  document.getElementById("statsNudge").textContent =
    dashboard?.motivation?.nudge || "Keep exploring.";
  document.getElementById("explorerXpTotal").textContent = `${fmt(xp)} XP total`;
  document.getElementById("explorerXpFill").style.width = `${pct}%`;
  document.getElementById("explorerXpCaption").textContent =
    toNext > 0 ? `${fmt(toNext)} XP to next level` : "Max curve for now";
  document.getElementById("statsTz").textContent = dashboard?.timezone
    ? `Stats · ${dashboard.timezone}`
    : "Stats";
}

function rateCaption(row) {
  if (row.rate == null) return "";
  const id = row.id || "";
  if (id === "tiles_new") return `${row.rate} XP / new tile`;
  if (id === "tiles_old") return `${row.rate} XP / revisit`;
  if (id === "wifi") return `${row.rate} XP / Wi‑Fi`;
  if (id === "bt") return `${row.rate} XP / Bluetooth`;
  if (id === "ble") return `${row.rate} XP / BLE`;
  return `${row.rate} XP each`;
}

function paintBreakdown() {
  const list = document.getElementById("xpBreakdownList");
  if (!list) return;
  const rows = progress?.breakdown || progress?.xp_activity?.breakdown || [];
  const total = Number(progress?.xp) || 0;
  if (!rows.length) {
    list.innerHTML = `<p class="muted">No XP yet — drive to unlock tiles and find networks.</p>`;
    return;
  }
  const maxXp = Math.max(1, ...rows.map((r) => Number(r.xp) || 0));
  list.innerHTML = rows
    .map((row) => {
      const xp = Number(row.xp) || 0;
      const width = Math.round((xp / maxXp) * 100);
      const count =
        row.count != null ? `<span class="xp-row-count">${fmt(row.count)}</span>` : "";
      const rate = rateCaption(row);
      return `
        <div class="xp-row">
          <div class="xp-row-head">
            <span class="xp-row-label">${row.label || row.id}</span>
            ${count}
            <span class="xp-row-xp">${fmt(xp)} XP</span>
          </div>
          <div class="meter xp-row-meter" aria-hidden="true">
            <div class="meter-fill" style="width:${width}%"></div>
          </div>
          ${rate ? `<p class="meter-caption">${rate}</p>` : ""}
        </div>`;
    })
    .join("");
  if (total > 0) {
    list.insertAdjacentHTML(
      "beforeend",
      `<p class="xp-breakdown-total muted">Sum ${fmt(
        rows.reduce((s, r) => s + (Number(r.xp) || 0), 0)
      )} XP · matches level total</p>`
    );
  }
}

/* —— Achievements (ported from achievements.js) —— */
function unitLabel(tier) {
  if (tier.unit_label) return tier.unit_label;
  const unit = tier.unit || "";
  if (unit.includes("km")) return "km";
  if (unit.includes("network") && unit.includes("starlink")) return "Starlink hotspots";
  if (unit.includes("network") && unit.includes("flipper")) return "Flipper Zeros";
  if (unit.includes("network")) return "networks";
  if (unit.includes("sample")) return "samples";
  if (unit.includes("segment")) return "tiles";
  return "";
}

function fmtNum(n, { km = false } = {}) {
  if (!Number.isFinite(n)) return "—";
  if (km) return n.toFixed(1);
  return Math.round(n).toLocaleString();
}

function fmtProgress(tier) {
  const cur = Number(tier.progress_raw ?? tier.progress ?? 0);
  const thr = Number(tier.threshold || 0);
  const label = unitLabel(tier);
  const km = label === "km";
  if (!thr) {
    const raw = km ? fmtNum(cur, { km: true }) : fmtNum(cur);
    return label ? `${raw} ${label}` : raw;
  }
  const left = km ? fmtNum(cur, { km: true }) : fmtNum(cur);
  const right = km ? fmtNum(thr, { km: true }) : fmtNum(thr);
  return label ? `${left} / ${right} ${label}` : `${left} / ${right}`;
}

function goalText(ach, tier) {
  return tier?.how || ach.description || "";
}

function pct(tier) {
  const thr = Number(tier.threshold || 0);
  if (!thr) return tier.unlocked ? 100 : 0;
  const cur = Number(tier.progress_raw ?? tier.progress ?? 0);
  return Math.max(0, Math.min(100, Math.round((cur / thr) * 100)));
}

function isMasteredTier(tier, tiers) {
  if (!tier) return false;
  if (tier.mastered) return true;
  if (!tier.unlocked) return false;
  if (tier.is_master_tier) return true;
  return !!tiers?.length && Number(tier.tier) >= tiers.length;
}

function statusLabel(tier, tiers) {
  if (tier?.status_label) return tier.status_label;
  if (isMasteredTier(tier, tiers)) return "Mastered";
  if (tier?.unlocked) return "Unlocked";
  return "Locked";
}

function defaultTierIndex(tiers) {
  if (!tiers?.length) return 0;
  const next = tiers.findIndex((t) => !t.unlocked);
  if (next >= 0) return next;
  return tiers.length - 1;
}

function applyTierView(card, ach, tierIndex) {
  const tiers = ach.tiers || [];
  const tier = tiers[tierIndex];
  if (!tier) return;

  const titleEl = card.querySelector("[data-ach-title]");
  const howEl = card.querySelector("[data-ach-how]");
  const badgeEl = card.querySelector("[data-ach-badge]");
  const fillEl = card.querySelector("[data-ach-fill]");
  const metaLeft = card.querySelector("[data-ach-meta-left]");
  const metaRight = card.querySelector("[data-ach-meta-right]");
  const xpEl = card.querySelector("[data-ach-xp]");

  const mastered = isMasteredTier(tier, tiers);
  const unlocked = !!tier.unlocked;

  if (titleEl) titleEl.textContent = tier.title || ach.title;
  if (howEl) howEl.textContent = goalText(ach, tier);
  if (badgeEl) {
    badgeEl.textContent = statusLabel(tier, tiers);
    badgeEl.classList.toggle("live", unlocked && !mastered);
    badgeEl.classList.toggle("mastered", mastered);
  }
  card.classList.toggle("is-unlocked", unlocked && !mastered);
  card.classList.toggle("is-mastered", mastered);
  card.classList.toggle("is-preview-locked", !unlocked);

  const p = pct(tier);
  if (fillEl) fillEl.style.width = `${p}%`;
  if (metaLeft) {
    metaLeft.textContent = mastered ? "Master tier" : `Tier ${tier.tier}`;
  }
  if (metaRight) metaRight.textContent = fmtProgress(tier);
  if (xpEl) {
    const xp = Number(tier.xp) || 0;
    xpEl.textContent = unlocked ? `+${xp} XP earned` : `+${xp} XP on unlock`;
    xpEl.classList.toggle("is-earned", unlocked);
    xpEl.classList.toggle("is-mastered", mastered);
  }

  card.querySelectorAll("[data-tier-idx]").forEach((btn) => {
    const i = Number(btn.dataset.tierIdx);
    const t = tiers[i];
    btn.classList.toggle("is-active", i === tierIndex);
    btn.classList.toggle("is-master", !!t && isMasteredTier(t, tiers));
    btn.setAttribute("aria-pressed", i === tierIndex ? "true" : "false");
  });

  card.dataset.selectedTier = String(tierIndex);
}

function renderAchievements(data) {
  const grid = document.getElementById("achGrid");
  const list = data.achievements || [];
  const xpEarned = Number(data.xp_earned) || 0;
  const xpAvail = Number(data.xp_available) || 0;
  const tz = data.timezone ? ` · ${data.timezone}` : "";
  document.getElementById("achSub").textContent =
    `${xpEarned.toLocaleString()} / ${xpAvail.toLocaleString()} XP from badges${tz}`;

  if (!list.length) {
    grid.innerHTML = `<p class="muted">No achievements catalog yet.</p>`;
    return;
  }

  grid.innerHTML = list
    .map((ach, achIdx) => {
      const tiers = ach.tiers || [];
      const sel = defaultTierIndex(tiers);
      const show = tiers[sel] || tiers[0];
      const unlockedN = tiers.filter((t) => t.unlocked).length;
      const tierN = tiers.length;
      const p = show ? pct(show) : 0;
      const xp = Number(show?.xp) || 0;
      const mastered = isMasteredTier(show, tiers);
      const unlocked = !!show?.unlocked;
      const flavour = ach.flavour
        ? `<p class="ach-flavour">${ach.flavour}</p>`
        : "";
      const pills = tiers
        .map(
          (t, i) => `
          <button type="button" class="ach-tier-pill ${i === sel ? "is-active" : ""} ${
            t.unlocked ? "is-done" : ""
          } ${isMasteredTier(t, tiers) ? "is-master" : ""}" data-tier-idx="${i}" aria-pressed="${
            i === sel
          }" title="${t.title}">
            ${t.is_master_tier || Number(t.tier) >= tierN ? "★" : t.tier}
          </button>`
        )
        .join("");

      return `
        <article class="ach-card ${
          mastered ? "is-mastered" : unlocked ? "is-unlocked" : "is-preview-locked"
        }"
          data-ach-idx="${achIdx}" data-selected-tier="${sel}">
          <div class="ach-card-top">
            <span class="module-kicker">${unlockedN}/${tierN} tiers</span>
            <span class="badge ${mastered ? "mastered" : unlocked ? "live" : ""}" data-ach-badge>${statusLabel(
              show,
              tiers
            )}</span>
          </div>
          <div class="ach-tier-row" role="group" aria-label="Tiers">${pills}</div>
          <h3 data-ach-title>${show?.title || ach.title}</h3>
          <p class="ach-how" data-ach-how>${goalText(ach, show)}</p>
          ${flavour}
          <div class="ach-xp ${unlocked ? "is-earned" : ""} ${mastered ? "is-mastered" : ""}" data-ach-xp>
            ${unlocked ? `+${xp} XP earned` : `+${xp} XP on unlock`}
          </div>
          <div class="ach-progress-track" aria-hidden="true">
            <div class="ach-progress-fill ${mastered ? "is-mastered" : ""}" data-ach-fill style="width:${p}%"></div>
          </div>
          <div class="ach-progress-meta">
            <span data-ach-meta-left>${mastered ? "Master tier" : `Tier ${show?.tier ?? "—"}`}</span>
            <span data-ach-meta-right>${show ? fmtProgress(show) : "—"}</span>
          </div>
        </article>`;
    })
    .join("");

  grid.querySelectorAll(".ach-card").forEach((card) => {
    const achIdx = Number(card.dataset.achIdx);
    const ach = list[achIdx];
    card.querySelectorAll("[data-tier-idx]").forEach((btn) => {
      btn.addEventListener("click", () => {
        applyTierView(card, ach, Number(btn.dataset.tierIdx));
      });
    });
  });
}

function paintRadios(system) {
  const k = system?.kismet || {};
  const wifi = k.wifi || {};
  const bt = k.bluetooth || {};
  const kEl = document.getElementById("radioKismet");
  const wEl = document.getElementById("radioWifi");
  const bEl = document.getElementById("radioBt");
  if (!kEl) return;

  if (k.http_ok || k.ok) {
    kEl.textContent = "Reachable";
  } else {
    kEl.textContent = k.detail || "Offline";
  }

  if (wifi.present && (wifi.interface || wifi.name)) {
    wEl.textContent = wifi.interface || wifi.name;
  } else if (wifi.present === false) {
    wEl.textContent = "none";
  } else {
    wEl.textContent = "—";
  }

  if (bt.present === true) {
    bEl.textContent = bt.interface ? `yes · ${bt.interface}` : "yes";
  } else if (bt.present === false) {
    bEl.textContent = "no";
  } else {
    bEl.textContent = "—";
  }
}

async function load() {
  const [dashRes, progRes, achRes, sysRes] = await Promise.all([
    WardAuth.apiFetch("/api/stats/dashboard"),
    WardAuth.apiFetch("/api/me/progress"),
    WardAuth.apiFetch("/api/achievements"),
    WardAuth.apiFetch("/api/system/status"),
  ]);

  if (dashRes.ok) {
    dashboard = await dashRes.json();
    paintPeriod();
    paintMeters();
    paintStreak();
    paintBest();
  } else {
    document.getElementById("statsHeadline").textContent = "Stats offline";
    document.getElementById("statsNudge").textContent = await dashRes.text();
  }

  if (progRes.ok) {
    progress = await progRes.json();
    paintExplorerHero();
    paintBreakdown();
  }

  if (achRes.ok) {
    renderAchievements(await achRes.json());
  } else {
    document.getElementById("achSub").textContent = "Could not load achievements";
  }

  if (sysRes.ok) {
    paintRadios(await sysRes.json());
  }

  if (location.hash === "#achievements") {
    document.getElementById("achievements")?.scrollIntoView({ behavior: "smooth" });
  }
}

document.querySelectorAll(".period-tab").forEach((btn) => {
  btn.addEventListener("click", () => setPeriod(btn.dataset.period));
});

(async () => {
  await WardAuth.requireAuth();
  load();
})();
