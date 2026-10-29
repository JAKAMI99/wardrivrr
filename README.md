# wardrivrr

![Version](https://img.shields.io/badge/version-1.0.0-0ea5e9)

**Discover your digital surroundings.** · **Version 1.0.0**

Local-first wardriving on OpenStreetMap: GPS unlocks road segments as you drive, the map shows what’s still unexplored, and offline routing points you toward streets you haven’t covered yet. Kismet fills in Wi‑Fi / Bluetooth sightings. Everything runs on your machine — PostGIS, UI, and routing — no cloud account.

---

## Screenshots

| Drive | Regions | Progress |
| --- | --- | --- |
| ![Drive / Navigate](docs/screenshots/drive.png) | ![Regions](docs/screenshots/regions.png) | ![Progress fog](docs/screenshots/progress.png) |
| Turn-by-turn into unexplored streets | Pick a place, download a map pack | Fog of war and XP |

| Status | Stats |
| --- | --- |
| ![Status](docs/screenshots/status.png) | ![Explorer stats](docs/screenshots/stats.png) |
| GPS, Kismet, routing, disk at a glance | Levels, achievements, radio totals |

Drop PNGs into `docs/screenshots/` (see that folder’s README). Until then the slots above are placeholders.

---

## Install

Product version (**1.0.0**) is shown in this README header, on the home page, and via `/api/health`. Image tag: **`:latest`**.

### Docker Compose (recommended)

One command. Optional: set a host data directory. No `.env` file. Wi‑Fi / Bluetooth / Kismet password are configured in the Web UI after login.

```bash
git clone https://github.com/JAKAMI99/wardrivrr.git
cd wardrivrr

# Persist data somewhere durable (absolute path recommended on a car):
export DATA_ROOT=/var/lib/wardrivrr
# Or omit DATA_ROOT to use ./data next to the compose file.

docker compose up -d
```

Then open `http://<host-ip>:8000/`:

1. **Setup** — create the admin password (no default login)
2. **Login** — as `admin`
3. **Machine setup** — dropdowns for Wi‑Fi, Bluetooth, optional GPS serial, Kismet password → **Apply & restart Kismet**
4. **Regions** → **Drive**

Health check:

```bash
curl -fsS http://127.0.0.1:8000/api/health
# → {"ok":true,"version":"1.0.0",...}
```

Requires Linux with Docker Compose v2 (API/Kismet use host networking for radio). Keep gpsd running on the host if you want live GPS (`127.0.0.1:2947`).

### Docker images

Published on GHCR. Compose defaults to `ghcr.io/jakami99/wardrivrr:latest`. Override if needed:

```bash
WARDRIVRR_IMAGE=ghcr.io/jakami99/wardrivrr:latest docker compose up -d
```

Local builds: `docker compose build api && docker compose up -d`.

### Manual install (bare metal)

Host API + PostGIS for development:

```bash
python -m venv venv
venv/bin/pip install -r backend/requirements.txt   # Windows: .\venv\Scripts\pip.exe …
docker compose up -d postgis
./debug.sh                                         # or .\debug.bat
```

Open `http://127.0.0.1:8000/setup`. Full Drive (Kismet / Valhalla / host GPS) is meant for the Compose path above.

---

## First boot

On a new install there is **no** default password. The UI redirects to `/setup` until you create the admin account (password, minimum 8 characters). Username is `admin`. After login, admins are sent to **Machine setup** until Wi‑Fi / Kismet are configured.

---

## Reset admin password

**Docker (vehicle stack):**

```bash
./scripts/reset-admin-password.sh 'YourNewPassword'
# Windows:
.\scripts\reset-admin-password.ps1 'YourNewPassword'
```

One-liner without the wrapper:

```bash
docker compose exec -T api \
  python /app/scripts/reset_admin_password.py 'YourNewPassword'
```

**Local debug:**

```bash
WARDRIVRR_RESET_LOCAL=1 ./scripts/reset-admin-password.sh 'YourNewPassword'
# or:
python scripts/reset_admin_password.py 'YourNewPassword'
```

Omit the password argument to be prompted interactively.

---

## Config notes

| Knob | Notes |
| --- | --- |
| `DATA_ROOT` | Host path for persistent data (map packs, Kismet conf/logs, JWT file, Valhalla). Default `./data`. Prefer an absolute path on a vehicle. |
| `WARDRIVRR_IMAGE` | Optional image override; default `ghcr.io/jakami99/wardrivrr:latest`. |
| Machine setup (Web UI) | Wi‑Fi / Bluetooth / Kismet password — stored under `$DATA_ROOT/machine.json` + `kismet/kismet_site.conf`. |
| JWT | Auto-written to `$DATA_ROOT/.jwt_secret` if unset. |

| Service | Port |
| --- | --- |
| API + UI | `8000` |
| Valhalla | `8002` |
| PostGIS | `5432` (bound `127.0.0.1`) |
| Kismet | `2501` |
| gpsd (host) | `2947` |

**Maps & routing:** create a **Region** in the UI → regional pack cached in `$DATA_ROOT/pbf/` (~7 days) → clip + Valhalla tiles → **Drive**. Live routing uses Valhalla tiles / `active.osm.pbf`, not the regional pack.

Ship checklist: [docs/SHIP_CHECKLIST.md](docs/SHIP_CHECKLIST.md).

---

## Layout

| Path | Role |
| --- | --- |
| `docker-compose.yml` | Single fire-and-forget stack |
| `debug.sh` / `debug.bat` | Host API via `run_dev.py` (dev) |
| `backend/` | FastAPI + `Dockerfile` |
| `frontend/` | Web UI (incl. `/machine-setup`) |
| `deploy/kismet/` | Default Kismet site conf template |
| `scripts/` | Helpers (wipe, ingest, password reset) |
| `$DATA_ROOT` | Map packs, Valhalla, Kismet logs/conf, `.jwt_secret` |
| `VERSION` | Product version (also home page / `/api/health`) |

---

## Credits

Upstream map, place, and MAC/OUI data: [CREDITS.md](CREDITS.md).

## License

[GPL-2.0](LICENSE)
