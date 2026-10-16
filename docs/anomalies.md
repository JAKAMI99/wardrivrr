# Special detections (anomalies)

Drive-mode Easter eggs for notable RF fingerprints. Rules live in
`backend/anomaly_rules.json` and are matched in `backend/anomalies.py` against
stored samples (`network_id` MAC, `name` SSID/BT name, `network_type`).

**Setting:** `user_settings.anomaly_alerts` (default **on**). Toggle in Settings
or the Navigate toolbar. When **off**: no drive toasts/sounds, and no credit
toward the **Transmitting to space** (Starlink) achievement.

---

## What we detect

| Id | How |
| :--- | :--- |
| `flipper_zero` | Wall of Flippers–style: Flipper Devices Inc BLE MAC OUIs `80:e1:26`, `80:e1:27`, `0c:fa:22`, or BT/BLE name starting with `flipper`. We do **not** store BLE service UUIDs (`00003081`…), so Identifier-only Flippers without those OUIs/names are missed. |
| `pwnagotchi` | Wi‑Fi beacon MAC `de:ad:be:ef:de:ad`, or SSID containing Pwnagotchi JSON fragments (`"pwnd`, `"identity"`, `"session_id"`). |
| `wifi_pineapple` | BSSID with middle bytes `13:37` (community / Hak5-adjacent detectors). Spoofed pools without that pattern are not matched. |
| `starlink` | Default SSID `STARLINK` or `STARLINK-*`. OUI omitted — Starlink randomizes BSSIDs. Renamed kits won’t match. |
| `train_wifionice` | Official DB SSID `WIFIonICE`. |
| `train_oebb` | Official ÖBB SSID `OEBB`. |

**Skipped / not reliable enough for v1**

* **SBB FreeSurf** — cellular tethering via the SBB app + Bluetooth, not a public train SSID.
* **HackRF / PortaPack** — no BT/Wi‑Fi beacon we store.
* Pineapple/Pwnagotchi variants that change MAC/SSID freely may evade these rules.

---

## Drive UX

On each `POST /api/gps/fix` with `session_started_at`, the server returns
`anomalies`: matching networks seen in `signal_samples` for that session.
Navigate shows a toast + short Web Audio blip (cooldown ~12s; each MAC/rule
pair toasted once per spawn).

---

## Achievement

**Transmitting to space** (`transmitting_to_space`) — 10 / 50 / 100 distinct
Starlink-matching networks for the user. Progress is counted only while
`anomaly_alerts` is enabled (see [achievement.md](achievement.md)).
