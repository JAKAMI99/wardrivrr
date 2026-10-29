(function () {
  const statusEl = document.getElementById("formStatus");
  const wifiSel = document.getElementById("wifiIface");
  const btSel = document.getElementById("btIface");
  const gpsSel = document.getElementById("gpsDevice");
  const userIn = document.getElementById("kismetUser");
  const passIn = document.getElementById("kismetPass");
  const form = document.getElementById("machineForm");
  const applyBtn = document.getElementById("applyBtn");

  function setStatus(msg, isError) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.classList.toggle("error", !!isError);
  }

  function fillSelect(sel, items, valueKey, labelFn, emptyLabel) {
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = "";
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = emptyLabel || "— none —";
    sel.appendChild(blank);
    for (const it of items || []) {
      const opt = document.createElement("option");
      const v = typeof it === "string" ? it : it[valueKey];
      opt.value = v;
      opt.textContent = labelFn ? labelFn(it) : v;
      sel.appendChild(opt);
    }
    if (cur) sel.value = cur;
  }

  async function load() {
    setStatus("Loading interfaces…");
    const me = await WardAuth.apiFetch("/api/auth/me");
    if (!me || !me.is_admin) {
      setStatus("Admin only — sign in as admin to configure the machine.", true);
      applyBtn.disabled = true;
      return;
    }
    const data = await WardAuth.apiFetch("/api/system/machine-setup");
    const nics = data.nics || [];
    const wifi = nics.filter((n) => n.kind === "wifi" || /^wl/i.test(n.name));
    const wifiList = wifi.length ? wifi : nics;
    fillSelect(
      wifiSel,
      wifiList,
      "name",
      (n) => `${n.name} (${n.kind})`,
      "— select Wi‑Fi —"
    );
    fillSelect(
      btSel,
      data.bluetooth || [],
      "name",
      (n) => n.name,
      "— none —"
    );
    fillSelect(
      gpsSel,
      data.serial || [],
      "path",
      (n) => n.path || n.name,
      "— none —"
    );

    const cfg = data.config || {};
    if (cfg.wifi_iface) wifiSel.value = cfg.wifi_iface;
    if (cfg.bluetooth_iface) btSel.value = cfg.bluetooth_iface;
    if (cfg.gps_device) gpsSel.value = cfg.gps_device;
    if (cfg.kismet_user) userIn.value = cfg.kismet_user;
    if (!cfg.has_password) passIn.value = "";
    setStatus(
      data.complete
        ? "Setup saved. Change anything below and apply again to restart Kismet."
        : "Choose interfaces and a Kismet password, then Apply."
    );
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    applyBtn.disabled = true;
    setStatus("Saving and restarting Kismet…");
    try {
      const body = {
        wifi_iface: wifiSel.value,
        bluetooth_iface: btSel.value,
        gps_device: gpsSel.value,
        kismet_user: userIn.value.trim(),
        kismet_password: passIn.value,
      };
      const res = await WardAuth.apiFetch("/api/system/machine-setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res || res.ok === false) {
        throw new Error((res && res.detail) || "Save failed");
      }
      const restartOk = res.restart && res.restart.ok;
      setStatus(
        restartOk
          ? "Saved. Kismet restarted — check Status."
          : `Saved config, but Kismet restart: ${(res.restart && res.restart.err) || "check docker.sock"}.`
      );
      if (restartOk) {
        setTimeout(() => {
          location.href = "/status";
        }, 1200);
      }
    } catch (err) {
      setStatus(err.message || String(err), true);
    } finally {
      applyBtn.disabled = false;
    }
  });

  WardAuth.requireAuth()
    .then(load)
    .catch((err) => setStatus(err.message || String(err), true));
})();
