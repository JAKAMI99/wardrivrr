# wardrivrr

Local-first wardriving explorer. Drive clears fog-of-war on mapped roads, optional Kismet captures RF, PostGIS stores progress, and Valhalla routes toward unexplored segments.

| Piece | Role |
|-------|------|
| **Web UI** | Phone/tablet HUD — Navigate, Levels, Status, Database |
| **API** | FastAPI (`backend/`) + static `frontend/` |
| **PostGIS** | Roads, fog unlock, networks, users |
| **Valhalla** | Offline turn-by-turn / explorer routing |
| **gpsd** (host) | USB GPS → API poller |
| **Kismet** (host) | Wi‑Fi / BT capture (not a default Docker service) |

Default login after a fresh database: `admin` / `admin` — change it.

---

## Requirements

**Vehicle / full stack (Linux)**

- Docker Engine + Compose v2
- Host `gpsd` (USB GNSS)
- Host [Kismet](https://www.kismetwireless.app/packages/) for live RF (installed by `./deploy.sh`)
- Disk for regional OSM packs + Valhalla tiles (`data/pbf/`, `data/valhalla/`)
- Network for first Geofabrik download (prefer home Wi‑Fi)

**Local development**

- Python 3.11+
- Docker only for PostGIS (and Valhalla if testing routing)

**Ports**

| Service | Port |
|---------|------|
| API + UI | `8000` |
| Valhalla | `8002` |
| PostGIS | `5432` |
| Kismet (host) | `2501` |
| gpsd (host) | `2947` |

---

## Quick deploy (recommended)

```bash
git clone https://github.com/JAKAMI99/wardrivrr.git
cd wardrivrr
./deploy.sh    # once: GPS / Wi‑Fi / BT prompts, .env, image, compose up
./run.sh       # later boots
```

Open `http://<host-ip>:8000/` → **Navigate**. Status: `http://<host-ip>:8000/status`.

Optional boot unit: edit paths in `deploy/wardrivrr-stack.service`, then:

```bash
sudo cp deploy/wardrivrr-stack.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wardrivrr-stack
```

Env templates: `.env.example`, `deploy/examples/.env.car.example`.

---

## Build the API image

From the **repo root** (Dockerfile expects this context):

```bash
docker build -f backend/Dockerfile -t wardrivrr-api:local .
```

CI publishes multi-arch images to GHCR (see `.github/workflows/docker-publish.yml`):

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
docker pull ghcr.io/<owner>/wardrivrr:latest
```

Set in `.env`:

```bash
WARDRIVRR_IMAGE=ghcr.io/<owner>/wardrivrr:latest
FORCE_LOCAL_BUILD=0
```

Or keep a local tag:

```bash
WARDRIVRR_IMAGE=wardrivrr-api:local
FORCE_LOCAL_BUILD=1
```

---

## Docker Compose

### Base (PostGIS + Valhalla)

```bash
cp .env.example .env   # edit DB_PASS, JWT, etc.
mkdir -p data/valhalla data/pbf
# Place or download a regional *.osm.pbf into data/pbf/, then seed:
#   ln data/pbf/SomeRegion.osm.pbf data/valhalla/active.osm.pbf
# or let ./run.sh seed the largest pack.

docker compose up -d postgis
# Start Valhalla only when data/valhalla/active.osm.pbf exists:
docker compose up -d valhalla
```

Compose file: `docker-compose.yml`  
Containers: `wardrivrr_postgis`, `wardrivrr_valhalla`.

### Full vehicle stack (API + overlay)

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/compose.car.yml \
  --env-file .env \
  up -d --build
```

That overlay:

- Builds/runs `wardrivrr_api` (`network_mode: host` so gpsd/Kismet on localhost work)
- Mounts `./data`, docker.sock, and the checkout for Valhalla recreate
- Leaves Kismet on the **host** (optional legacy profile: `--profile kismet-docker`)

Everyday equivalent: `./run.sh`.

Stop:

```bash
docker compose -f docker-compose.yml -f deploy/compose.car.yml --env-file .env stop
```

---

## Manual `docker run`

Use these when composing by hand. Prefer Compose for volumes and healthchecks.

### PostGIS

```bash
docker volume create wardrivrr_pgdata

docker run -d --name wardrivrr_postgis --restart unless-stopped \
  -e POSTGRES_DB=wardriving \
  -e POSTGRES_USER=explorer \
  -e POSTGRES_PASSWORD=change_me_strong \
  -p 5432:5432 \
  -v wardrivrr_pgdata:/var/lib/postgresql/data \
  -v "$(pwd)/postgis/init:/docker-entrypoint-initdb.d:ro" \
  postgis/postgis:16-3.4
```

### Valhalla

Requires a non-empty `data/valhalla/active.osm.pbf` (seed from `data/pbf/*.osm.pbf` first). Do **not** bind-mount a missing file path — Docker would create a directory.

```bash
mkdir -p data/valhalla
# seed: ln -f data/pbf/YourRegion.osm.pbf data/valhalla/active.osm.pbf

docker run -d --name wardrivrr_valhalla --restart unless-stopped \
  -p 8002:8002 \
  -e use_tiles_ignore_pbf=False \
  -e serve_tiles=True \
  -e build_elevation=False \
  -e build_admins=False \
  -e build_time_zones=False \
  -e server_threads=4 \
  -v "$(pwd)/data/valhalla:/custom_files" \
  ghcr.io/gis-ops/docker-valhalla/valhalla:latest
```

First start builds tiles; watch with `docker logs -f wardrivrr_valhalla`.

### API (+ frontend)

Host network matches the vehicle overlay (gpsd / Kismet on `127.0.0.1`):

```bash
docker run -d --name wardrivrr_api --restart unless-stopped \
  --network host \
  --env-file .env \
  -e DB_HOST=127.0.0.1 \
  -e DB_PORT=5432 \
  -e VALHALLA_URL=http://127.0.0.1:8002 \
  -e GPSD_HOST=127.0.0.1 \
  -e KISMET_URL=http://127.0.0.1:2501 \
  -e DATA_ROOT=/app/data \
  -e HOST_DATA_ROOT="$(pwd)/data" \
  -e WARDRIVRR_COMPOSE_ROOT=/host/project \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/data/kismet_logs:/data/kismet_logs:ro" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(pwd):/host/project:ro" \
  wardrivrr-api:local
```

Bridge mode (dev / no host gpsd) — map port 8000 and point `DB_HOST` at the PostGIS container or host IP:

```bash
docker run -d --name wardrivrr_api --restart unless-stopped \
  -p 8000:8000 \
  --env-file .env \
  -e DB_HOST=host.docker.internal \
  -e VALHALLA_URL=http://host.docker.internal:8002 \
  -e GPSD_ENABLED=0 \
  -e KISMET_LIVE=0 \
  -e DATA_ROOT=/app/data \
  -v "$(pwd)/data:/app/data" \
  --add-host=host.docker.internal:host-gateway \
  wardrivrr-api:local
```

Health: `curl -fsS http://127.0.0.1:8000/api/health`

---

## Local debug (host API)

```bash
python -m venv venv
# Linux/macOS
venv/bin/pip install -r backend/requirements.txt
./debug.sh
# Windows
.\venv\Scripts\pip.exe install -r backend\requirements.txt
.\debug.bat
```

`./debug.sh --database` — Status treats GPS / Kismet / Valhalla as N/A.

PostGIS only: `docker compose up -d postgis`

---

## Map data

1. Download a Geofabrik region (UI or drop `*.osm.pbf` into `data/pbf/`).
2. `./run.sh` (or first level create) seeds `data/valhalla/active.osm.pbf` and builds tiles.
3. Creating a level can clip the pack to the level bbox and rebuild.

Drive routing needs Valhalla HTTP up (`:8002`). Pre-seed at home if the vehicle link is a phone hotspot.

---

## Layout

| Path | Role |
|------|------|
| `deploy.sh` / `run.sh` | First-time setup / everyday boot |
| `debug.sh` / `debug.bat` | Host API via `run_dev.py` |
| `backend/` | FastAPI + `Dockerfile` |
| `frontend/` | Web UI |
| `deploy/` | Compose overlay, systemd, Kismet examples |
| `scripts/` | Ingest / migration helpers |
| `tools/drive_sim/` | Replay without live GPS |
| `postgis/init/` | DB bootstrap SQL |
| `data/` | PBF packs, Valhalla tiles, Kismet logs (gitignored) |

---

## Credits

Upstream map and place data: [CREDITS.md](CREDITS.md).
