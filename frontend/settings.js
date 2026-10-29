const toast = document.getElementById("toast");

function fmt(n) {
  if (n == null || Number.isNaN(Number(n))) return "-";
  return new Intl.NumberFormat().format(n);
}

function showToast(message, isError = false) {
  toast.hidden = false;
  toast.textContent = message;
  toast.classList.toggle("error", isError);
}

async function loadSettings() {
  const res = await WardAuth.apiFetch("/api/settings");
  const data = await res.json();
  if (!res.ok) return;
  document.getElementById("precision").value = data.default_localize_precision || "balanced";
  document.getElementById("nightly").checked = !!data.localize_nightly;
  document.getElementById("anomalyAlerts").checked =
    data.anomaly_alerts !== false && data.anomaly_alerts !== "false";
  const snd = document.getElementById("achievementSounds");
  if (snd) {
    snd.checked =
      data.achievement_sounds !== false && data.achievement_sounds !== "false";
  }
  const sonar = document.getElementById("driveSonar");
  if (sonar) {
    sonar.checked =
      data.drive_sonar !== false && data.drive_sonar !== "false";
  }
  document.getElementById("units").value = data.units === "imperial" ? "imperial" : "metric";
  const mapDark = document.getElementById("mapDarkMode");
  if (mapDark) {
    const mode = String(data.map_dark_mode || "auto").toLowerCase();
    mapDark.value = ["auto", "bright", "dark", "system"].includes(mode)
      ? mode
      : "auto";
  }
  if (data.theme && window.WardTheme) {
    WardTheme.apply(data.theme, { persist: true, broadcast: true });
  }
}

async function loadExplorerXp() {
  try {
    const res = await WardAuth.apiFetch("/api/me/progress");
    const prog = await res.json().catch(() => null);
    if (!res.ok || !prog) return;
    const wrap = document.getElementById("settingsXp");
    if (!wrap) return;
    wrap.hidden = false;
    const lvl = document.getElementById("settingsXpLevel");
    const pts = document.getElementById("settingsXpPoints");
    const fill = document.getElementById("settingsXpFill");
    const blurb = document.getElementById("settingsXpBlurb");
    if (lvl) lvl.textContent = `Level ${prog.level}`;
    if (pts) pts.textContent = `${fmt(prog.xp)} XP`;
    if (fill) fill.style.width = `${Math.min(100, Number(prog.progress_pct) || 0)}%`;
    if (blurb) {
      blurb.textContent = `${fmt(prog.xp_to_next)} XP to level ${prog.level + 1} · from unlocked achievements`;
    }
  } catch {
    /* optional */
  }
}

function escHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function loadWigleCredentials() {
  const hint = document.getElementById("wigleConfiguredHint");
  try {
    const res = await WardAuth.apiFetch("/api/wigle/credentials", {
      redirectOn401: false,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return;
    const help = document.querySelector(".help-tip[href*='wigle.net']");
    if (help && data.account_url) help.href = data.account_url;
    if (hint) {
      if (data.configured) {
        hint.hidden = false;
        hint.textContent = `Saved key · ${data.api_key_suffix || "****"}`;
      } else {
        hint.hidden = true;
        hint.textContent = "";
      }
    }
  } catch {
    /* optional */
  }
}

function readWigleApiKey() {
  return document.getElementById("wigleApiKey")?.value?.trim() || "";
}

async function loadKeys() {
  const res = await WardAuth.apiFetch("/api/keys");
  const keys = await res.json().catch(() => []);
  const el = document.getElementById("keysList");
  if (!res.ok || !keys.length) {
    el.innerHTML = `<p class="muted">No API keys yet.</p>`;
    return;
  }
  el.innerHTML = keys
    .map(
      (k) => `
    <div class="key-row">
      <span>${escHtml(k.name)} · <code>${escHtml(k.key_prefix)}...</code>
        ${k.revoked_at ? " (revoked)" : ""}</span>
      ${
        k.revoked_at
          ? ""
          : `<button class="btn" data-revoke="${k.id}" type="button">Revoke</button>`
      }
    </div>`
    )
    .join("");
  el.querySelectorAll("[data-revoke]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await WardAuth.apiFetch(`/api/keys/${btn.dataset.revoke}`, { method: "DELETE" });
      loadKeys();
    });
  });
}

async function loadAdmin(user) {
  if (!user.is_admin) return;
  const navBtn = document.getElementById("adminNavBtn");
  if (navBtn) navBtn.hidden = false;
}

const SETTINGS_SECTIONS = [
  "account",
  "preferences",
  "data",
  "admin",
];

function showSettingsSection(id) {
  const section = SETTINGS_SECTIONS.includes(id) ? id : "account";
  if (section === "admin" && document.getElementById("adminNavBtn")?.hidden) {
    return showSettingsSection("account");
  }
  document.querySelectorAll(".settings-nav-btn").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.section === section);
  });
  document.querySelectorAll(".settings-panel").forEach((panel) => {
    const on = panel.dataset.section === section;
    panel.classList.toggle("is-active", on);
    panel.hidden = !on;
  });
  if (location.hash.replace(/^#/, "") !== section) {
    history.replaceState(null, "", `#${section}`);
  }
}

function bindSettingsNav() {
  document.querySelectorAll(".settings-nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => showSettingsSection(btn.dataset.section));
  });
  window.addEventListener("hashchange", () => {
    showSettingsSection(location.hash.replace(/^#/, "") || "account");
  });
}

function fillAccountUsername(user) {
  const el = document.getElementById("accountUsername");
  if (el && user?.username) el.value = user.username;
}

function setWhoami(user) {
  const el = document.getElementById("whoami");
  if (!el || !user) return;
  el.textContent = `Signed in as ${user.username}${user.is_admin ? " (admin)" : ""}`;
}

document.getElementById("settingsForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const theme = window.WardTheme ? WardTheme.read() : "classic";
  const res = await WardAuth.apiFetch("/api/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      default_localization_mode: "2d",
      default_localize_precision: document.getElementById("precision").value,
      localize_nightly: document.getElementById("nightly").checked,
      anomaly_alerts: document.getElementById("anomalyAlerts").checked,
      achievement_sounds: document.getElementById("achievementSounds")?.checked ?? true,
      drive_sonar: document.getElementById("driveSonar")?.checked ?? true,
      units: document.getElementById("units").value,
      map_dark_mode: document.getElementById("mapDarkMode")?.value || "auto",
      theme,
    }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(body.detail || "Save failed", true);
    return;
  }
  if (body.theme && window.WardTheme) {
    WardTheme.apply(body.theme, { persist: true, broadcast: true });
  }
  showToast("Settings saved");
});

document.getElementById("recomputeNow").addEventListener("click", async () => {
  const precision = document.getElementById("precision").value;
  if (!window.confirm(`Queue full localization (2d, ${precision})?`)) return;
  const res = await WardAuth.apiFetch("/api/localize/recompute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "2d", precision, async_job: true }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(body.detail || "Failed", true);
    return;
  }
  showToast(body.queued ? `Queued job #${body.job_id}` : `Updated ${fmt(body.updated)}`);
});

document.getElementById("createKey").addEventListener("click", async () => {
  const res = await WardAuth.apiFetch("/api/keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: document.getElementById("keyName").value || "default" }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(body.detail || "Create failed", true);
    return;
  }
  const pre = document.getElementById("newKey");
  pre.hidden = false;
  pre.textContent = `Copy now: ${body.key}`;
  loadKeys();
});

function setBusy(btn, progressEl, barEl, textEl, busy, label) {
  if (!btn) return;
  btn.disabled = busy;
  btn.classList.toggle("is-busy", busy);
  btn.classList.toggle("is-done", false);
  if (progressEl) progressEl.hidden = !busy;
  if (textEl && label) textEl.textContent = label;
  if (barEl && busy) {
    barEl.style.width = "15%";
    barEl.classList.add("indeterminate");
  }
  if (barEl && !busy) {
    barEl.classList.remove("indeterminate");
  }
}

function finishBusy(btn, progressEl, barEl, textEl, okMessage) {
  if (barEl) {
    barEl.classList.remove("indeterminate");
    barEl.style.width = "100%";
  }
  if (textEl) textEl.textContent = okMessage;
  btn.classList.remove("is-busy");
  btn.classList.add("is-done");
  btn.disabled = false;
  setTimeout(() => {
    if (progressEl) progressEl.hidden = true;
    if (barEl) barEl.style.width = "0%";
    btn.classList.remove("is-done");
  }, 1200);
}

function pulseProgress(barEl, textEl, phases) {
  let i = 0;
  const id = setInterval(() => {
    if (!barEl || !barEl.classList.contains("indeterminate")) {
      clearInterval(id);
      return;
    }
    i = (i + 1) % phases.length;
    if (textEl) textEl.textContent = phases[i];
    barEl.style.width = `${20 + ((i + 1) / phases.length) * 55}%`;
  }, 900);
  return id;
}

document.getElementById("wigleSaveBtn")?.addEventListener("click", async () => {
  const api_key = readWigleApiKey();
  if (!api_key) {
    showToast("Paste your WiGLE Encoded for Use API key", true);
    return;
  }
  const res = await WardAuth.apiFetch("/api/wigle/credentials", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key }),
    redirectOn401: false,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "Could not save WiGLE key";
    showToast(detail, true);
    return;
  }
  document.getElementById("wigleApiKey").value = "";
  await loadWigleCredentials();
  showToast("WiGLE API key saved");
});

document.getElementById("wigleImportBtn")?.addEventListener("click", async () => {
  const btn = document.getElementById("wigleImportBtn");
  const progress = document.getElementById("wigleImportProgress");
  const bar = document.getElementById("wigleImportProgressBar");
  const text = document.getElementById("wigleImportProgressText");
  const api_key = readWigleApiKey();
  const payload = { skip_existing: true };
  if (api_key) payload.api_key = api_key;
  setBusy(btn, progress, bar, text, true, "Listing WiGLE uploads…");
  if (bar) {
    bar.classList.remove("indeterminate");
    bar.style.width = "2%";
  }
  let summary = null;
  try {
    const res = await WardAuth.apiFetch("/api/wigle/import", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
      body: JSON.stringify(payload),
      redirectOn401: false,
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      setBusy(btn, progress, bar, text, false);
      const detail =
        typeof errBody.detail === "string" ? errBody.detail : "WiGLE import failed";
      showToast(detail, true);
      return;
    }
    const reader = res.body?.getReader?.();
    if (!reader) {
      setBusy(btn, progress, bar, text, false);
      showToast("WiGLE import: no response stream", true);
      return;
    }
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        let ev;
        try {
          ev = JSON.parse(line);
        } catch {
          continue;
        }
        if (ev.message && text) text.textContent = ev.message;
        if (ev.stage === "file" && ev.total && bar) {
          const pct = Math.max(2, Math.min(99, (Number(ev.current) / Number(ev.total)) * 100));
          bar.style.width = `${pct}%`;
        } else if (ev.stage === "listed" && bar) {
          bar.style.width = "5%";
        }
        if (ev.stage === "done") summary = ev;
        if (ev.stage === "error") {
          setBusy(btn, progress, bar, text, false);
          showToast(ev.message || "WiGLE import failed", true);
          return;
        }
      }
    }
    if (api_key) {
      document.getElementById("wigleApiKey").value = "";
      await loadWigleCredentials();
    }
    if (!summary) {
      setBusy(btn, progress, bar, text, false);
      showToast("WiGLE import finished with no summary", true);
      return;
    }
    finishBusy(
      btn,
      progress,
      bar,
      text,
      `Done · ${fmt(summary.files_ingested)}/${fmt(summary.transactions)} files · ${fmt(summary.samples_submitted)} samples`
    );
    const skipped = summary.skipped_existing
      ? ` · ${fmt(summary.skipped_existing)} skipped`
      : "";
    showToast(
      `WiGLE: ${fmt(summary.files_ingested)} files · ${fmt(summary.samples_submitted)} samples${skipped}`
    );
    if (summary.failed_count) {
      showToast(`${fmt(summary.failed_count)} file(s) failed — check Status / logs`, true);
    }
  } catch (err) {
    setBusy(btn, progress, bar, text, false);
    showToast(String(err), true);
  }
});

document.getElementById("uploadBtn").addEventListener("click", async () => {
  const file = document.getElementById("uploadFile").files[0];
  if (!file) {
    showToast("Choose a file first", true);
    return;
  }
  const btn = document.getElementById("uploadBtn");
  const progress = document.getElementById("uploadProgress");
  const bar = document.getElementById("uploadProgressBar");
  const text = document.getElementById("uploadProgressText");
  setBusy(btn, progress, bar, text, true, "Uploading & ingesting...");
  const pulse = pulseProgress(bar, text, [
    "Uploading...",
    "Detecting format...",
    "Writing samples...",
    "Localizing networks...",
  ]);
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await WardAuth.apiFetch("/api/v1/ingest/upload", { method: "POST", body: fd });
    const body = await res.json().catch(() => ({}));
    clearInterval(pulse);
    if (!res.ok) {
      setBusy(btn, progress, bar, text, false);
      showToast(body.detail || "Upload failed", true);
      return;
    }
    finishBusy(
      btn,
      progress,
      bar,
      text,
      `Done · ${fmt(body.samples_submitted)} samples`
    );
    showToast(
      `Ingested ${body.format}: ${fmt(body.samples_submitted)} samples -> ${fmt(body.networks_updated)} networks`
    );
  } catch (err) {
    clearInterval(pulse);
    setBusy(btn, progress, bar, text, false);
    showToast(String(err), true);
  }
});

document.getElementById("exportBtn").addEventListener("click", async () => {
  const kind = document.getElementById("exportKind").value;
  const btn = document.getElementById("exportBtn");
  const progress = document.getElementById("exportProgress");
  const bar = document.getElementById("exportProgressBar");
  const text = document.getElementById("exportProgressText");
  setBusy(btn, progress, bar, text, true, "Collecting your data...");
  const pulse = pulseProgress(bar, text, [
    "Collecting samples...",
    "Packing networks...",
    "Building archive...",
    "Almost ready...",
  ]);
  try {
    const res = await WardAuth.apiFetch("/api/backup/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind }),
    });
    clearInterval(pulse);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setBusy(btn, progress, bar, text, false);
      showToast(body.detail || "Export failed", true);
      return;
    }
    if (text) text.textContent = "Downloading...";
    if (bar) bar.style.width = "92%";
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `wardrivrr_${kind}.zip`;
    a.click();
    URL.revokeObjectURL(a.href);
    finishBusy(btn, progress, bar, text, "Export ready");
    showToast("Export downloaded");
  } catch (err) {
    clearInterval(pulse);
    setBusy(btn, progress, bar, text, false);
    showToast(String(err), true);
  }
});

document.getElementById("importBtn").addEventListener("click", async () => {
  const file = document.getElementById("importFile").files[0];
  const mode = document.getElementById("importMode").value;
  if (!file) {
    showToast("Choose a backup zip", true);
    return;
  }
  if (mode === "replace" && !window.confirm("Replace will delete your current samples/networks. Continue?")) {
    return;
  }
  const btn = document.getElementById("importBtn");
  const progress = document.getElementById("importProgress");
  const bar = document.getElementById("importProgressBar");
  const text = document.getElementById("importProgressText");
  setBusy(btn, progress, bar, text, true, "Reading backup...");
  const pulse = pulseProgress(bar, text, [
    "Reading archive...",
    "Merging samples...",
    "Restoring networks...",
    "Finishing up...",
  ]);
  const fd = new FormData();
  fd.append("file", file);
  fd.append("mode", mode);
  try {
    const res = await WardAuth.apiFetch("/api/backup/import", { method: "POST", body: fd });
    const body = await res.json().catch(() => ({}));
    clearInterval(pulse);
    if (!res.ok) {
      setBusy(btn, progress, bar, text, false);
      showToast(body.detail || "Import failed", true);
      return;
    }
    finishBusy(
      btn,
      progress,
      bar,
      text,
      `Imported · ${fmt(body.networks)} networks`
    );
    showToast(`Imported samples=${fmt(body.samples)} networks=${fmt(body.networks)}`);
  } catch (err) {
    clearInterval(pulse);
    setBusy(btn, progress, bar, text, false);
    showToast(String(err), true);
  }
});

document.getElementById("inviteForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const invitePass = document.getElementById("invitePass").value;
  if (invitePass.length < 8) {
    showToast("Password must be at least 8 characters", true);
    return;
  }
  const res = await WardAuth.apiFetch("/api/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: document.getElementById("inviteUser").value.trim(),
      password: invitePass,
      is_admin: document.getElementById("inviteAdmin").checked,
    }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(body.detail || "Invite failed", true);
    return;
  }
  showToast(`Created ${body.username}`);
  document.getElementById("inviteForm")?.reset();
});

document.getElementById("usernameForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("accountUsername").value.trim();
  const res = await WardAuth.apiFetch("/api/auth/username", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(body.detail || "Could not change username", true);
    return;
  }
  if (body.access_token) {
    const remember =
      body.keep_logged_in ??
      (localStorage.getItem("wardrivrr_remember") === "1");
    WardAuth.setToken(body.access_token, !!remember);
  }
  if (body.user) {
    setWhoami(body.user);
    fillAccountUsername(body.user);
    document.querySelectorAll(".account-name").forEach((el) => {
      el.textContent = body.user.username;
    });
    const ini = String(body.user.username || "?").slice(0, 2).toUpperCase();
    document.querySelectorAll(".account-avatar").forEach((el) => {
      el.textContent = ini;
    });
  }
  showToast(`Username is now ${body.user?.username || username}`);
});

document.getElementById("passwordForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const current = document.getElementById("currentPassword").value;
  const next = document.getElementById("newPassword").value;
  const confirm = document.getElementById("confirmPassword").value;
  if (next.length < 8) {
    showToast("Password must be at least 8 characters", true);
    return;
  }
  if (next !== confirm) {
    showToast("New passwords do not match", true);
    return;
  }
  const res = await WardAuth.apiFetch("/api/auth/password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      current_password: current,
      new_password: next,
    }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(body.detail || "Could not change password", true);
    return;
  }
  document.getElementById("passwordForm").reset();
  showToast("Password updated");
});

(async () => {
  const user = await WardAuth.requireAuth();
  if (!user) return;
  setWhoami(user);
  fillAccountUsername(user);
  bindSettingsNav();
  await loadSettings();
  await loadWigleCredentials();
  await loadExplorerXp();
  await loadKeys();
  await loadAdmin(user);
  showSettingsSection(location.hash.replace(/^#/, "") || "account");
})();
