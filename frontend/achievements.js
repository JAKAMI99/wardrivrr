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
    metaLeft.textContent = mastered
      ? "Master tier"
      : `Tier ${tier.tier}`;
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

function render(data) {
  const grid = document.getElementById("achGrid");
  const list = data.achievements || [];
  const xpEarned = Number(data.xp_earned) || 0;
  const xpAvail = Number(data.xp_available) || 0;
  const tz = data.timezone ? ` · ${data.timezone}` : "";
  document.getElementById("achSub").textContent =
    `${xpEarned.toLocaleString()} / ${xpAvail.toLocaleString()} XP${tz}`;

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

(async () => {
  const user = await WardAuth.requireAuth();
  if (!user) return;
  const res = await WardAuth.apiFetch("/api/achievements");
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    document.getElementById("achSub").textContent =
      data.detail || "Could not load achievements";
    return;
  }
  render(data);
})();
