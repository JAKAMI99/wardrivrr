# wardrivrr

**Drive real roads. Clear the fog. Route into the dark.**

Local-first wardriving on OpenStreetMap: GPS unlocks road segments as you drive, the map shows what’s still unexplored, and offline routing points you toward streets you haven’t covered yet. Kismet fills in Wi‑Fi / Bluetooth sightings. Everything runs on your machine — PostGIS, UI, and routing — no cloud account.

Default login after a fresh database: `admin` / `admin` — change it.

---

## What you get

- **Fog of war** — driven roads light up; never-driven stay dark
- **Navigate** — turn-by-turn toward unexplored segments (Valhalla, local)
- **Levels** — pick a place, download a map pack, play that area
- **XP & achievements** — progress from exploration (tiles), not busywork
- **Status** — GPS, Kismet, routing, and disk at a glance

---

## Quick deploy (vehicle / Linux)

```bash
git clone https://github.com/JAKAMI99/wardrivrr.git
cd wardrivrr
chmod +x deploy.sh run.sh
./deploy.sh    # once: Docker, gpsd, Kismet prompts, .env, stack up
./run.sh       # everyday boot
```

Open `http://<host-ip>:8000/` → create a **Level**, then **Navigate**.

Optional boot unit: edit paths in `deploy/wardrivrr-stack.service`, then:

```bash
sudo cp deploy/wardrivrr-stack.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wardrivrr-stack
```

Env templates: `.env.example`, `deploy/examples/.env.car.example`.

---

## Maps & routing (how it actually works)

You don’t hand-seed Valhalla.

1. In the UI, create a **Level** (city or district) — one map per place.
2. The API downloads a regional Geofabrik pack into `data/pbf/` and imports the **full playable road graph** (every vehicle mode).
3. When the level is ready, Valhalla gets a **clip of that place only**, builds tiles for it, and starts on `:8002`.
4. In **Navigate**, pick Big car / Small car / Bike / Foot — that filters fog, explore targets, and dead-end policy. Do not create a second level for the same area.

The regional pack stays in `data/pbf/` for indexing and future levels. It is **not** what Valhalla tiles — that was making builds crawl.

`data/valhalla/` is runtime state (active clip + tiles). App-managed.

---

## Requirements

| | |
|--|--|
| **Vehicle** | Docker Engine + Compose v2, host `gpsd`, host [Kismet](https://www.kismetwireless.app/packages/) (via `./deploy.sh`), disk for map packs |
| **Dev** | Python 3.11+, Docker for PostGIS (Valhalla only if you test routing) |

| Service | Port |
|---------|------|
| API + UI | `8000` |
| Valhalla | `8002` |
| PostGIS | `5432` |
| Kismet (host) | `2501` |
| gpsd (host) | `2947` |

---

## Local debug (host API)

```bash
python -m venv venv
venv/bin/pip install -r backend/requirements.txt   # or Windows: .\venv\Scripts\pip.exe …
./debug.sh                                         # or .\debug.bat
```

`./debug.sh --database` — Status treats GPS / Kismet / Valhalla as N/A.  
PostGIS only: `docker compose up -d postgis`.

---

## Docker (short form)

**Image** (from repo root):

```bash
docker build -f backend/Dockerfile -t wardrivrr-api:local .
```

Or pull GHCR and set `WARDRIVRR_IMAGE=ghcr.io/<owner>/wardrivrr:latest` in `.env` (`FORCE_LOCAL_BUILD=0`).

**Vehicle stack** (same as `./run.sh`):

```bash
docker compose -f docker-compose.yml -f deploy/compose.car.yml --env-file .env up -d
```

Compose starts **Valhalla** only when `data/valhalla/active.osm.pbf` already exists from a prior level. Empty checkout → API + PostGIS until the first level is ready.

Containers: `wardrivrr_api`, `wardrivrr_postgis`, `wardrivrr_valhalla`.

---

## Layout

| Path | Role |
|------|------|
| `deploy.sh` / `run.sh` | First-time setup / everyday boot |
| `debug.sh` / `debug.bat` | Host API via `run_dev.py` |
| `backend/` | FastAPI + `Dockerfile` |
| `frontend/` | Web UI |
| `deploy/` | Compose overlay, systemd, Kismet examples |
| `scripts/` | Helpers (Docker ensure, wipe, ingest, `prepare_offline_data.py`) |
| `docker/prepare-data.sh` | Download cities / postal / IEEE OUI / Geofabrik index into `data/` |
| `tools/drive_sim/` | Replay without live GPS |
| `postgis/init/` | DB bootstrap SQL |
| `data/` | Map packs, Valhalla runtime, Kismet logs (gitignored) |

---

## Credits

Upstream map, place, and MAC/OUI data: [CREDITS.md](CREDITS.md).
