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

## Quick start

### Vehicle / Linux (recommended)

First boot installs host helpers, writes `.env`, and brings the stack up:

```bash
git clone https://github.com/JAKAMI99/wardrivrr.git
cd wardrivrr
chmod +x deploy.sh run.sh scripts/reset-admin-password.sh
./deploy.sh
```

Everyday boot (gpsd + Kismet + compose):

```bash
./run.sh
```

Open `http://<host-ip>:8000/` — first boot redirects to **Setup** (create the admin password). Then sign in as `admin`, create a **Region**, then **Drive**.

Optional systemd unit (paths rewritten by `./run.sh`):

```bash
sudo cp deploy/wardrivrr-stack.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wardrivrr-stack
```

### Docker Compose only (after `.env` exists)

Same stack `./run.sh` uses — root compose + car overlay:

```bash
cp .env.example .env
# Set DB_PASS, HOST_PROJECT, HOST_DATA_ROOT (absolute clone paths), KISMET_PASSWORD, …
mkdir -p data/kismet_logs data/valhalla data/incoming data/pbf

docker compose -f docker-compose.yml -f deploy/compose.car.yml --env-file .env up -d --build
```

Health check:

```bash
curl -fsS http://127.0.0.1:8000/api/health
# → {"ok":true,"version":"1.0.0",...}
```

Open UI / Swagger:

- UI: `http://127.0.0.1:8000/`
- Setup (fresh DB): `http://127.0.0.1:8000/setup`
- Swagger: `http://127.0.0.1:8000/api/docs`

Verify persistence mounts (must survive recreate):

```bash
docker compose -f docker-compose.yml -f deploy/compose.car.yml --env-file .env config | grep -E 'data|pgdata'
# Host: ./data → /app/data (map packs, JWT file, user data)
# Named volume: pgdata (PostGIS)
ls -la data/
```

### Local debug (host API)

```bash
python -m venv venv
venv/bin/pip install -r backend/requirements.txt   # Windows: .\venv\Scripts\pip.exe …
docker compose up -d postgis
./debug.sh                                         # or .\debug.bat
```

Open `http://127.0.0.1:8000/setup` on a fresh database.

---

## First boot

On a new install there is **no** default password. The UI redirects to `/setup` until you create the admin account (password, minimum 8 characters). Username is `admin`. After that, use `/login` as usual. All other routes and APIs stay blocked until setup completes.

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
docker compose -f docker-compose.yml -f deploy/compose.car.yml exec -T api \
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

| Variable | Notes |
| --- | --- |
| `JWT_SECRET_KEY` | Optional. If unset, the API writes a random secret to `data/.jwt_secret` (persisted via the `./data` mount). |
| `DB_PASS` | Required for real deploys. `deploy.sh` generates a strong value on fresh installs; change the `.env.example` placeholder before shipping. |
| `HOST_PROJECT` / `HOST_DATA_ROOT` | Absolute host paths required for the car overlay (Valhalla via docker.sock). `./run.sh` / `./deploy.sh` write these. |
| `GPSD_*` / `KISMET_*` | Host services; car overlay uses host networking. |
| `WARDRIVRR_VERSION` | Optional override; defaults to the repo `VERSION` file (`1.0.0`). |

| Service | Port |
| --- | --- |
| API + UI | `8000` |
| Valhalla | `8002` |
| PostGIS | `5432` (default bind `127.0.0.1`) |
| Kismet (host) | `2501` |
| gpsd (host) | `2947` |

**Maps & routing:** create a **Region** in the UI → regional Geofabrik pack in `data/pbf/` → clip + Valhalla tiles for that place only → **Drive**. Do not create a second region for the same area.

Compose starts **Valhalla** only when `data/valhalla/active.osm.pbf` already exists from a prior region. Empty checkout → API + PostGIS until the first region is ready.

Env templates: `.env.example`, `deploy/examples/.env.car.example`.

Ship checklist: [docs/SHIP_CHECKLIST.md](docs/SHIP_CHECKLIST.md).

---

## Layout

| Path | Role |
| --- | --- |
| `deploy.sh` / `run.sh` | First-time setup / everyday boot |
| `debug.sh` / `debug.bat` | Host API via `run_dev.py` |
| `backend/` | FastAPI + `Dockerfile` |
| `frontend/` | Web UI |
| `deploy/` | Compose overlay, systemd, Kismet examples |
| `scripts/` | Helpers (Docker ensure, wipe, ingest, password reset, offline data) |
| `data/` | Map packs, Valhalla runtime, Kismet logs, `.jwt_secret` (gitignored) |
| `VERSION` | Release version (`1.0.0`) |

---

## Credits

Upstream map, place, and MAC/OUI data: [CREDITS.md](CREDITS.md).

## License

[GPL-2.0](LICENSE)
