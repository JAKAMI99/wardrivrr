# wardrivrr

Local wardriving explorer: Drive (turn-by-turn fog-of-war), Kismet RF, PostGIS, Valhalla.

## Car mini-PC (Linux)

```bash
git clone <your-private-repo-url> wardrivrr
cd wardrivrr
# Install Docker Engine yourself first, then:
./scripts/car_setup.sh    # interactive Wi-Fi / BT / GPS + GHCR pull
./scripts/car_up.sh       # later boots (pull GHCR, compose up, gpsd check)
```

Open `http://<mini-ip>:8000/` → **Navigate**. GPS from gpsd auto-follows; generate a level when prompted.

Full risk list & morning checklist: [docs/CAR_DEPLOY_HANDOFF.md](docs/CAR_DEPLOY_HANDOFF.md)

### Trusted images (GitHub Actions → GHCR)

API + static frontend are built by CI and published to **GitHub Container Registry** — not a hand-rolled laptop image.

| Trigger | Tags |
|---------|------|
| Push to `main` / `master` | `latest`, `sha-<short>` |
| Tag `v*` | semver (`1.2.3`, `1.2`) + sha |

Workflow: [`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml)

```bash
# Private package — PAT with read:packages
echo $GITHUB_TOKEN | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
docker pull ghcr.io/<owner>/wardrivrr:latest
```

Set `WARDRIVRR_IMAGE=ghcr.io/<owner>/wardrivrr:latest` in `.env`.  
`car_setup.sh` / `car_up.sh` **prefer GHCR pull**; local `docker compose build` is fallback only (`FORCE_LOCAL_BUILD=1`).

Verify: image digest should match the Actions run on GitHub → Packages / workflow logs.

## Dev (Windows / host API)

```bash
python -m venv venv
.\venv\Scripts\pip.exe install -r backend\requirements.txt
.\venv\Scripts\python.exe run_dev.py
```

PostGIS + Valhalla: `docker compose up -d postgis valhalla`

## Layout

| Path | Role |
|------|------|
| `backend/` | FastAPI (+ `Dockerfile` for API+frontend) |
| `frontend/` | WebUI |
| `docs/` | All documentation |
| `deploy/` | Car compose overlay + examples |
| `scripts/` | `car_setup.sh`, `car_up.sh`, ingest helpers |
| `tools/drive_sim/` | Kismet replay for testing without GPS |
| `postgis/init/` | DB bootstrap SQL |
| `backups/` | Local export copies (gitignored) |
| `.github/workflows/` | GHCR publish |

Default login after fresh DB: `admin` / `admin` (change it).
