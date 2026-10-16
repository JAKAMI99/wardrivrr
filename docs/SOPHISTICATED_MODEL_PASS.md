# Sophisticated model pass — leftover / high-risk polish

Feed this file (+ [CAR_DEPLOY_HANDOFF.md](CAR_DEPLOY_HANDOFF.md)) to a **strong / expensive** model for final cleanup. Do **not** ask it to review the entire repo.

---

## Brief for expensive models (read this first)

### What wardrivrr is (30 seconds)

Local wardriving / fog-of-war explorer: phone HUD (**Navigate**), PostGIS road unlock, Valhalla routing, Kismet RF ingest, gpsd on the **host**. Car stack = Docker (API+UI, PostGIS, Valhalla, Kismet) + host gpsd. Trusted app image from **GitHub Actions → GHCR**, not laptop-built by default.

### Crash course — only these paths

| Concern | Read |
|---------|------|
| Morning ops / risks | `docs/CAR_DEPLOY_HANDOFF.md` |
| App image CI | `.github/workflows/docker-publish.yml`, `deploy/compose.car.yml`, `scripts/car_up.sh` |
| GPS → snap → unlock | `backend/gpsd_poller.py`, `backend/gps_snap.py`, `backend/levels.py` (`unlock_near_point`), `backend/gps_state.py` |
| Drive HUD | `frontend/navigate.js` (wrong-way streak, snap 8 m, auto-follow) |
| Live RF | `backend/kismet_live.py`, `backend/live_ingest.py` |
| XP | `backend/achievements.py` (`explorer_progress*`), Home/Settings XP UI |

Skip themes, address indexes, historical docs, and unrelated frontend pages unless a bug forces it.

### Hard constraints (do not “fix”)

- **`GPS_SNAP_THRESHOLD_M` default 8, hard max 10** — good receiver; rail lag is meters. Never widen to 25–40.
- gpsd stays on **host**; Kismet live is primary, kis_db fallback.
- Prefer **patching open risks** below over new features (no deauth detectors, no big UI rewrites).

### Mission for this pass (token-budget)

1. Multi-arch GHCR if mini-PC is arm64 (or confirm amd64-only + document).  
2. Kismet live: auth + watermark + no duplicate ingest.  
3. Navigate: auto-explore retry; wrong-way hysteresis still sane.  
4. Snap: highway-class filter / parallel-road edge **without** raising threshold.  
5. Compose/`DATA_ROOT` / shell CRLF / default `admin` banner if cheap wins.

**Out of scope:** full architecture redesign, theme polish, new RF attack detectors.

---


## 1. CI / supply chain (GHCR)

**Now:** [`.github/workflows/docker-publish.yml`](../.github/workflows/docker-publish.yml) builds one `linux/amd64,linux/arm64` manifest, pushes to `ghcr.io/${{ github.repository }}`, emits provenance + SBOM + build attestation, and keyless-signs the pushed digest with cosign.

**Still needed:**

| Task | Why | Acceptance |
|------|-----|------------|
| **Multi-arch `linux/amd64,linux/arm64` — shipped** | Mini-PCs are often ARM (RPi / some NUCs) | Workflow includes both; handoff documents CI time/storage tradeoff |
| **Cosign / keyless signing — shipped** | Prove image wasn’t swapped | Signs on push; `cosign verify` is in CAR_DEPLOY_HANDOFF |
| **Pin digest — supported** | `latest` moves | Set `WARDRIVRR_IMAGE=ghcr.io/…/wardrivrr@sha256:…`; handoff has example |
| **Package visibility** | Private GHCR auth friction | Doc: classic PAT scopes vs fine-grained; `car_setup` fail message if 401 |
| **Owner placeholder** | `compose.car.yml` default `ghcr.io/OWNER/wardrivrr` | Scripts already rewrite; ensure empty OWNER never silently pulls wrong public image |

---

## 2. Kismet live bridge

**Files:** [`backend/kismet_live.py`](../backend/kismet_live.py), [`backend/live_ingest.py`](../backend/live_ingest.py)

| Edge case | Acceptance |
|-----------|------------|
| REST field lists / endpoint differ by Kismet version | Probe `/system/status.json`, fall through known device URLs; log which path worked |
| Auth: Basic vs cookie session — shipped | Probe status with Basic; reuse a cookie when supplied; setup writes matching credentials |
| WebSocket `devices/monitor.ws` as primary | Optional WS with REST poller as backup; no duplicate samples |
| Dedup memory / restarts — shipped | Bounded LRU by `(mac, last_time)`; REST and kis_db watermarks persist in `user_settings` |
| Device without GPS + gpsd gap | Queue or drop with metric; Status page shows live ingest rate |
| kis_db fallback re-ingests whole file | Incremental by `last_time` / rowid watermark in `user_settings` or file |
| Session binding | Observations use same `session_started_at` as gpsd poller for HUD “new” |

**Test:** With Kismet up, Drive HUD Wi‑Fi new/seen rises without file upload; Database map shows networks within ~30s.

---

## 3. gpsd poller races

**Files:** [`backend/gpsd_poller.py`](../backend/gpsd_poller.py), [`backend/gps_state.py`](../backend/gps_state.py)

| Issue | Acceptance |
|-------|------------|
| Multi-user car: who gets the fix? | Document single-driver; `GPSD_USER_ID` wins; don’t overwrite sim users mid-debug |
| `record_drive_step` + `unlock_near_point` every 1 Hz | Cap DB load; batch unlock; don’t block socket read |
| Heading hold vs U-turn | Hysteresis when speed crosses `0.4 m/s`; unit test with parked TPV |
| Session start never resets | Reset session when Navigate sets `navigation_active` false→true or new spawn |

---

## 4. Navigate auto-drive / wrong-way

**Files:** [`frontend/navigate.js`](../frontend/navigate.js), [`frontend/navigate.html`](../frontend/navigate.html)

| Issue | Acceptance |
|-------|------------|
| Auto-explore before Valhalla ready — shipped | Retries with capped exponential backoff; marks started only after a route succeeds |
| Wrong-way streak vs soft corridor — shipped, road-test pending | Separate counters; any good fix resets both; no replan under `WRONG_WAY_STREAK_N` |
| GPS lag 180° flip for 2–3 s | No TBT flash / replan (manual road test) |
| `?debug=1` only | Production: no Spawn/Follow/hint clutter; icons zoom/buildings work on touch |
| Phone geolocation fallback | Best-effort if gpsd dead (optional); never preferred over gpsd |
| Tesla WebGL fail | Graceful message + 2D fallback or “open on phone” |

---

## 5. Explorer XP / level

**Files:** [`backend/achievements.py`](../backend/achievements.py) (`explorer_progress*`), [`frontend/home.js`](../frontend/home.js), Settings account panel

| Issue | Acceptance |
|-------|------------|
| Curve only from achievement XP | Document; optional drive-km bonus later without double-count |
| `list_achievements` re-eval on every progress GET | Cache or lighter SQL for `/api/me/progress` |
| Home XP strip styling across themes | CRT / kidcore readable; link to `/achievements` |
| Level chip on Drive HUD | Already stub `statXpLevel` — keep in sync on unlock toast |

---

## 6. Sounds

**Files:** navigate.js `playAchievementSound` / `playAnomalySound`, settings `achievement_sounds`

| Issue | Acceptance |
|-------|------------|
| AudioContext gesture policy | Unlock on first tap; queue sounds until then |
| Mute persists | Settings + Navigate both respect; reduced-motion skips |
| Spam on batch unlocks | One sting per toast batch (already); cap loudness |

---

## 7. Docker / car compose

**Files:** [`backend/Dockerfile`](../backend/Dockerfile), [`deploy/compose.car.yml`](../deploy/compose.car.yml), [`scripts/car_*.sh`](../scripts/)

| Issue | Acceptance |
|-------|------------|
| Kismet image name / tag drift | Pin digest or known-good tag; document privileged + host net |
| `kismet_site.conf` missing → kismet crash loop | car_up checks file exists |
| Data volume path `/app/data` vs code expecting repo-relative `data/` | Align `paths.py` / env `DATA_ROOT` |
| Healthcheck needs `curl` in image | Present in Dockerfile; confirm |
| Windows CRLF on `car_*.sh` | `.gitattributes` `*.sh text eol=lf` |

---

## 8. Security hardening

| Issue | Acceptance |
|-------|------------|
| Default `admin`/`admin` | Force password change on first login or Status banner |
| JWT + Kismet passwords in `.env` | Never commit; rotate doc in handoff |
| API bound `0.0.0.0` on hotspot | Accept for car; optional basic auth / VPN note |
| Privileged Kismet | Document blast radius |

---

## 9. Testing gaps

| Test | Path / how |
|------|------------|
| Unit: XP curve | `xp_for_level` / `level_from_xp` table of values |
| Unit: wrong-way streak | Pure JS extract or small node test |
| Integration: gpsd mock TCP | Fake TPV JSON → `set_fix` |
| Integration: Kismet REST fixture | Recorded devices.json → ingest counts |
| Manual: car_up pull 401 → build fallback | Script exits 0 and stack runs |

---

## 10. Docs / cleanup leftovers

- Update [`docs/FRONTEND.md`](FRONTEND.md) / [`docs/BACKEND.md`](BACKEND.md) for auto-drive, XP, live Kismet, GHCR.
- Confirm no root markdown sprawl (only `README.md`).
- [`docs/achievement.md`](achievement.md): document explorer level curve explicitly.
- Remove unused `_file_offsets` in `kismet_live.py` or implement watermark.

---

## 11. GPS snap-to-road (rail / lag) — shipped tight; harden edges

**Now:** [`backend/gps_snap.py`](../backend/gps_snap.py) + [`gpsd_poller.py`](../backend/gpsd_poller.py) + `POST /api/gps/fix` + Navigate `applyRouteSnap` / `SNAP_TO_ROAD_M = 8`.

| Knob | Default |
|------|---------|
| `GPS_SNAP_THRESHOLD_M` (alias `SNAP_TO_ROAD_M`) | **8 m** (hard-capped at **10**) |
| `GPS_SNAP_HEADING_PREF_DEG` | 55° |
| `GPS_SNAP_ENABLED` | 1 |
| Frontend route polish | 8 m |

**Behavior:** Within threshold → `ST_ClosestPoint` on `road_segments` (heading-biased). Beyond → **hold last good** if ≤3× threshold, else **raw** (`degraded`). **Unlock uses snapped lat/lon.** Icon shows server snap (+ optional route polish).

**Do not** widen default above 10 m — receiver is good; rail lag is meters, not tens of meters.

| Edge case | Acceptance |
|-----------|------------|
| Parallel road vs rail within ~8 m | Heading bias picks road aligned with travel; road-test next to rail; add highway-class filter if still wrong |
| Tunnel / brief no-road — shipped | Hold last snapped for 6 s (hard max 8) then degrade to raw; don’t jump across gap |
| Wrong highway type (footpath snap) — shipped | Restrict to car-profile highways when level profile is `car` |
| ST_ClosestPoint at 1 Hz | Spatial index + bbox pad; measure on full level; cache last segment |
| Server snap vs client route snap | Prefer `fix.snapped` / `fix.snap`; client polish only for HUD |
| Hysteresis thrashing | Optional sticky segment id for N fixes before switching parallels |
| Valhalla `/trace_route` map-match | Optional secondary when PostGIS miss but Valhalla tiles warm |

---

## Priority order for the stronger model

1. **At home:** run `car_up.sh` on the actual mini; confirm native GHCR pull and API health  
2. **Stationary smoke:** Kismet auth + live devices + HUD counters for 2 minutes; confirm restart does not duplicate samples  
3. **Short local loop:** auto-explore waits for Valhalla, then starts without a tap; no replan from a 2–3 s heading flip  
4. **Rail/parallel-road loop:** confirm car-highway filter + 6 s tunnel hold; keep snap at 8 m (hard max 10)  
5. Freeze tomorrow’s tested `WARDRIVRR_IMAGE` to its `@sha256:` digest  
6. Everything else only after the drive path passes
