# Module: Mobile-first WebUI (`FRONTEND.md`)

## Role

The frontend is the control surface for wardrivrr. It targets **phones and tablets first**, and also works as a full tool on desktop browsers — including a device on a local hotspot while moving.

### Routes
* `/login` — Invite-only JWT sign-in (bootstrap `admin` / `admin`).
* `/` — Home: compact service chips, Wi‑Fi / BT / BLE counts, modules.
* `/database` — Signal database explorer (map search & filters).
* `/stats` — Gamified explorer stats (today / 7d / all-time, streaks, milestones). XP later.
* `/levels` — Geofabrik levels (local city search, profile, download, road stats).
* `/api` — Triangulated DB search (SSID / MAC / place / ZIP) + curl; Swagger at `/api/docs`.
* `/status` — Full system status (gpsd, Kismet, Valhalla, PostGIS, storage).
* `/settings` — Localization precision, API keys, upload, export/import, admin invites.

Auth: `frontend/auth.js` attaches `Authorization: Bearer` from localStorage. See `docs/MULTIUSER.md`.

### Deployment modes
* `WARDIVRR_MODE=full` (default) — GPS / Kismet / routing expected (red/yellow if down).
* `WARDIVRR_MODE=database` — home-server mode; those services show **N/A (gray)**.

### System status API
* `GET /api/system/status` — includes `deployment.mode` / `expected`, per-service `state` (`ok|warn|down|na`).

Optimised for touch, modest device resources, and clear map feedback (Fog of War, filters, gamification later).

---

## Stack

| Piece | Tech | Why |
| :--- | :--- | :--- |
| UI | Static HTML/JS (Leaflet today; Vite/React optional later) | Small, fast to load on mobile |
| Map | Leaflet (+ clustering) | Thousands of markers without melting a phone |
| Styling | CSS variables / themes | Live theme switch |
| Realtime | WebSockets (planned) | Live GPS / unlocks |
| Offline | IndexedDB (planned) | Cache tiles/snippets |

---

## Features

### Fog-of-War map (planned)
* Unexplored vs explored segments with high-contrast colours.
* Auto-pan / heading when live GPS is available.

### Live HUD
* Stats, filters, network markers from derived locations.
* Opt-in **3D location recalculation** (not default; may take time).

### Signals ticker (planned)
* Live Wi-Fi / BLE detections.

---

## API

* `GET /api/explore` — GeoJSON of derived networks.
* `GET /api/health`, `GET /api/stats`
* `POST /api/localize/recompute` — `{ "mode": "3d" }` for opt-in 3D.
