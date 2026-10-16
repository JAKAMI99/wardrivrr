# Achievements (`achievement.md`)

Wardrivrr turns movement and capture into unlockable badges. Progress is tracked
locally per user (PostGIS). Toasts fire on unlock while navigating; the catalog is
served by `GET /api/achievements` (Stats UI can list them).

See also: [IDEA.md](IDEA.md) exploration loop.

---

## Design principles

* **Local only** — no cloud leaderboards by default.
* **Honest meters** — drive distance comes from successive GPS/sim fixes while
  navigating (or live gpsd later), not from crow-flies cheating across teleports.
* **Timezone** — “today” and night hours use `STATS_TZ` / `ACHIEVEMENTS_TZ`
  (default `Europe/Berlin`).
* **Tiers** — one achievement id, multiple thresholds. Unlocking tier 2 does not
  remove tier 1; both stay earned. The Achievements UI lets you preview any tier
  (including locked) and updates the goal copy + progress bar for that threshold.
* **Units & how** — each tier exposes `unit_label` (`km` / `networks` / `samples`)
  and a short `how` goal string (e.g. “Drive 42 km in one calendar day”).
* **XP** — each tier grants a fixed XP reward on unlock (`xp` in the catalog).
  `GET /api/achievements` returns `xp_earned` / `xp_available` plus `explorer` progress.
* **Explorer level** — derived from `xp_earned` only (single source of truth). Cumulative XP to reach level `L` (L≥1) is `100 * (L-1) * L / 2` (level 1 = 0 XP). API: `GET /api/me/progress` → `{ xp, level, xp_into_level, xp_to_next, progress_pct }`. Shown on Home + Settings.
* **Idempotent** — re-evaluating never doubles an unlock.

---

## Drive accounting

| Counter | Meaning |
| :--- | :--- |
| `drive_day_km.km_total` | Kilometres driven that calendar day |
| `drive_day_km.km_night` | Of which between **00:00–06:00** local |
| `drive_day_km.km_explored` | Road-km unlocked that day (from segment unlocks) |

Each GPS fix with a previous fix within 2 minutes adds haversine distance
(capped per tick so a jump does not grant a marathon).

Capture counts use `networks` and `signal_samples.altitude`.

---

## Catalog

### Night owl (`night_owl`)

Drive after midnight. Cumulative night kilometres (00:00–06:00). Unit: **km**.

| Tier | How | Title |
| :---: | :--- | :--- |
| 1 | Drive 50 km between 00:00–06:00 | Night owl |
| 2 | Drive 200 km between 00:00–06:00 | Night owl II |
| 3 | Drive 500 km between 00:00–06:00 | Night owl III |

Flavour: *The APs never sleep. Neither do you.*

---

### Memelord (`memelord`)

One calendar day, total driven kilometres. Unit: **km**.

| Tier | How | Title |
| :---: | :--- | :--- |
| 1 | Drive 42 km in one calendar day | Memelord |
| 2 | Drive 67 km in one calendar day | Memelord II |
| 3 | Drive 133.7 km in one calendar day | Memelord III |

Flavour: *42 → 67 → 133.7. Respect the lore.*

---

### Hack all the things (`hack_all_the_things`)

Collect triangulated **networks** in your local database (all types counted). Unit: **networks**.

| Tier | How | Title |
| :---: | :--- | :--- |
| 1 | Collect 50,000 triangulated networks | Hack all the things |
| 2 | Collect 200,000 triangulated networks | Hack all the things II |
| 3 | Collect 500,000 triangulated networks | Hack all the things III |

Flavour: *More boxes. More packets. More everything.*

---

### Aden Pierce (`aden_pierce`)

Unit: **networks**.

| Tier | How | Title |
| :---: | :--- | :--- |
| 1 | Collect 1,000,000 triangulated networks | Aden Pierce |

Flavour: *ctOS would be proud. Probably.*

---

### Below sea (`below_sea`)

Unit: **samples**.

| Tier | How | Title |
| :---: | :--- | :--- |
| 1 | Collect 500 observation points below 0 m altitude | Below sea |

Flavour: *Dead reckoning in the bathyscape.*

---

### Mountainclimber (`mountainclimber`)

Unit: **samples**.

| Tier | How | Title |
| :---: | :--- | :--- |
| 1 | Collect 500 observation points above 700 m altitude | Mountainclimber |

Flavour: *Thin air, thick RF.*

---

### Transmitting to space (`transmitting_to_space`)

Distinct networks matching the Starlink SSID rules (`STARLINK` / `STARLINK-*`).
Unit: **Starlink hotspots**. Progress only advances while **Special detections**
(`anomaly_alerts`) is enabled — see [anomalies.md](anomalies.md).

| Tier | How | Title |
| :---: | :--- | :--- |
| 1 | Detect 10 distinct Starlink hotspots | Transmitting to space |
| 2 | Detect 50 distinct Starlink hotspots | Transmitting to space II |
| 3 | Detect 100 distinct Starlink hotspots | Transmitting to space III |

Flavour: *Low Earth orbit, high RSSI envy.*

---

## API

* `GET /api/achievements` — catalog + user progress / unlocked list  
* Progress is refreshed on GPS fix (`POST /api/gps/fix`) and can be forced with
  `POST /api/achievements/evaluate` (also useful after a big ingest)

---

## Future ideas (not shipped)

* **Fog eater** — unlock 10 / 50 / 100 km of road segments  
* **Dead-end tourist** — visit N cul-de-sacs in one session  
* **District completionist** — 100% explored on a district level  
* **Theme badges** — tied to Classic Sleek / CRT / Kawaii selectors  
* Optional encrypted sync of achievement state in Phase 3 multi-client
