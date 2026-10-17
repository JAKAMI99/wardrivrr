# Car deploy handoff (morning checklist)

Use this on the mini-PC before a real drive. Deeper leftover polish: [SOPHISTICATED_MODEL_PASS.md](SOPHISTICATED_MODEL_PASS.md).

## Morning checklist

1. **Power / sleep** — disable suspend while driving (`systemctl mask sleep.target` or DE setting).
2. **Time** — NTP on (`timedatectl`); wrong clock breaks JWT + “today” XP.
3. **Disk** — `df -h` (kis_db + PostGIS + Valhalla grow fast).
4. **USB** — Alfa Wi‑Fi, GPS dongle, optional BT. Note tty (`ls /dev/ttyUSB* /dev/ttyACM*`).
5. **gpsd** — `systemctl status gpsd` then `cgps -s` outdoors until 3D fix.
6. **Stack** — `./scripts/car_up.sh` (**local Docker build** by default, starts compose, checks gpsd). Optional GHCR pull if you set `FORCE_LOCAL_BUILD=0`.
7. **Status UI** — `http://<mini-ip>:8000/status` → GPS ok, Kismet running, DB ok, Valhalla up.
8. **Kismet** — `http://<mini-ip>:2501/` → devices appearing on Alfa iface (not empty).
9. **Drive** — phone browser → `/navigate` → map follows GPS without tapping Follow; auto-explore when level ready.
10. **Hotspot IP** — re-check mini IP if Tesla/phone can’t reach bookmark.

## How to run the car stack

```bash
cd ~/wardrivrr   # or your clone path
./scripts/car_setup.sh   # first time only
./scripts/car_up.sh      # every boot
```

### Auto-start on boot

Compose services use `restart: unless-stopped` (containers come back after reboot **if Docker itself starts**):

```bash
sudo systemctl enable --now docker
sudo systemctl enable --now gpsd
sudo systemctl enable --now wardrivrr-kismet   # host Kismet
# Optional: full stack via car_up on boot
sudo cp deploy/wardrivrr-stack.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wardrivrr-stack
```

### Kismet config

Leave `/etc/kismet/kismet.conf` mostly stock. Put **all** car overrides in `/etc/kismet/kismet_site.conf` (see `deploy/kismet/kismet_site.conf.teslian`). Remove duplicate `source=` / `gps=` lines from `kismet.conf` so they don’t fight the site file.

Compose:

```bash
docker compose -f docker-compose.yml -f deploy/compose.car.yml --env-file .env up -d
```

| Service | Port | Notes |
|---------|------|--------|
| API + UI | **8000** | Prefer `ghcr.io/<owner>/wardrivrr` from GitHub Actions |
| Kismet | **2501** | **host apt + systemd** (`wardrivrr-kismet`) — not Docker |
| PostGIS | 5432 | internal + host publish |
| Valhalla | 8002 | tiles from `data/valhalla/active.osm.pbf` (seeded/clipped from `data/pbf/*.osm.pbf`) |
| **gpsd** | **2947** | **host systemd only** — not a container |

API reaches host gpsd / Kismet via `host.docker.internal` (`extra_hosts: host-gateway`).

## Docker image — local build by default

`car_setup.sh` / `car_up.sh` **build on the mini** (`WARDRIVRR_IMAGE=wardrivrr-api:local`, `FORCE_LOCAL_BUILD=1`).

Your user must reach the Docker socket (otherwise `permission denied … docker.sock`):

```bash
sudo usermod -aG docker "$USER"
newgrp docker   # or log out and back in
docker info     # must work without sudo
```

Optional later: CI images from [`.github/workflows/docker-publish.yml`](../.github/workflows/docker-publish.yml) → `ghcr.io/<owner>/wardrivrr` (amd64+arm64). Opt in during setup (“Prefer GHCR?”) or set `FORCE_LOCAL_BUILD=0` + `WARDRIVRR_IMAGE=ghcr.io/…` in `.env`.

## GPS / Kismet notes

- **gpsd on host** — car_setup writes `/etc/default/gpsd` for the chosen tty. The API poller reads gpsd at **`GPSD_POLL_INTERVAL` (default 0.2 s ≈ 5 Hz)**. Heading = TPV `track` (held when parked).
- **Snap-to-road (rail / GPS lag)** — Backend [`gps_snap.py`](../backend/gps_snap.py) projects fixes onto level `road_segments` within **`GPS_SNAP_THRESHOLD_M` (default 8 m, hard max 10; alias `SNAP_TO_ROAD_M`)**. The 10 m cap also applies to direct caller overrides. Heading bias (`GPS_SNAP_HEADING_PREF_DEG`, default 55°) prefers edges aligned with travel, and car levels reject non-car highway classes. **Snapped lat/lon are used for the Navigate vehicle icon and for fog/tile unlock** (`unlock_near_point` in gpsd poller + `POST /api/gps/fix`). Beyond threshold: hold the last good snap only while still nearby and for at most 6 seconds (`GPS_SNAP_HOLD_MAX_S`, hard max 8), then use **raw GPS**. Frontend route polish remains **8 m**. Disable: `GPS_SNAP_ENABLED=0`. Do **not** widen above 10 m.
- **Kismet on host** — there is **no** working public `kismetwireless/kismet` Docker Hub image. `car_setup.sh` installs Kismet from [kismetwireless apt](https://www.kismetwireless.app/packages/) and enables `wardrivrr-kismet.service`. Compose does not pull a Kismet container by default (`profiles: [kismet-docker]` only). API talks to `host.docker.internal:2501`.
- **Kismet live** — API polls REST on `:2501` → `live_ingest`. File `.kismet` / `kis_db` under `data/kismet_logs/` is fallback + post-drive import.
- **Wrong iface** — internal `wlan0` vs Alfa ruins capture; setup prompt is mandatory; confirm devices in Kismet UI.
- **Curl smoke** (after Kismet user exists):

```bash
curl -u "$KISMET_USER:$KISMET_PASSWORD" "http://127.0.0.1:2501/system/status.json"
curl -u "$KISMET_USER:$KISMET_PASSWORD" "http://127.0.0.1:2501/devices/last-time/-30/devices.json" | head
```

## Tesla / phone caveats

- **Phone is the real HUD.** Tesla browser is best-effort (WebGL / MapLibre may fail or stutter).
- Hotspot IP changes — don’t rely on a stale bookmark alone.
- Production Navigate chrome is icons-only (zoom ±, 3D buildings). Debug: `/navigate?debug=1`.

## Pre-seed OSM / Valhalla (do this at home Wi‑Fi)

First level generate on a phone hotspot can take **tens of minutes** and burn data.

1. On a fat link, download a Geofabrik region (UI or drop `*.osm.pbf` into `data/pbf/` — names stay like `Arnsberg….osm.pbf`, never `active`).
2. First pack download (or `./scripts/car_up.sh`) seeds `data/valhalla/active.osm.pbf` and starts a full Valhalla tile rebuild.
3. Creating a level then clips that pack to the level bbox and rebuilds again (smaller/faster).
4. Copy `data/pbf/` + `data/valhalla/` to the mini before the trip if you pre-built at home.
5. Drive won’t route until Valhalla HTTP is up — watch Status / Navigate overlay / `docker logs -f wardrivrr_valhalla`.

## PostGIS init “Permission denied”

If logs show `psql: …/01_schema.sql: Permission denied`, the container user cannot read `postgis/init/*.sql` on the host. Fix and **recreate the empty volume** (init only runs once):

```bash
chmod a+rx postgis postgis/init
chmod a+r postgis/init/*.sql
docker compose -f docker-compose.yml -f deploy/compose.car.yml --env-file .env down
docker volume rm wardrivrr_pgdata
docker compose -f docker-compose.yml -f deploy/compose.car.yml --env-file .env up -d
```

## DB wipe note (this machine)

Backups were confirmed under `backups/` before `docker compose down -v` during cleanup. If you wipe again: export from Settings first, copy zips off-box, then `down -v`.

## Ranked risks (will ruin the drive)

1. No GPS fix / wrong tty  
2. Wrong Wi‑Fi iface  
3. First PBF/level on hotspot  
4. Kismet live auth/WS fail → drive moves but no RF on HUD (ingest `.kismet` later)  
5. Tesla browser choke  
6. Hotspot IP drift  
7. Disk full  
8. Suspend mid-drive  
9. Clock skew  
10. GHCR auth / SSH clone keys missing — have USB copy of repo as Plan B  

## Reminder for Balduin

You are tired. Do **not** invent features on the road. Fallback: gpsd + map movement + file ingest after the drive. Feed leftover edge cases to a stronger model via [SOPHISTICATED_MODEL_PASS.md](SOPHISTICATED_MODEL_PASS.md).
