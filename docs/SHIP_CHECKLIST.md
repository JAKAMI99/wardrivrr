# Ship checklist

Tracker for a professional ship of **wardrivrr 1.0.0**. Sourced from [REVIEW.md](REVIEW.md) plus this hardening pass. Update as items land.

Release: **1.0.0** · Status: **Done** · **User tonight** · **Open**

---

## Done (this ship pass)

- [x] Remove `admin`/`admin` bootstrap; first-boot web setup at `/setup`
- [x] Public `GET /api/setup/status`, one-shot `POST /api/setup/admin`
- [x] Block normal use until setup complete (middleware + frontend redirect)
- [x] Min password length 8 (API + settings / invite / setup UI)
- [x] `JWT_SECRET_KEY` from env or auto `data/.jwt_secret` (no hardcoded default)
- [x] Admin password reset scripts (`scripts/reset-admin-password.sh` / `.ps1` + Python helper)
- [x] README rewrite (pitch, screenshots slots, quick start, first boot, reset, Docker, config, license)
- [x] Compose / `.env.example` no longer ship a JWT placeholder default
- [x] Grep-clean default `admin`/`admin` from docs and drive_sim defaults
- [x] Login + setup rate limit (IP+bucket)
- [x] Region rebuild restores explored fog by `osm_id`
- [x] Geocode: no permanent miss cache; coalesce no longer forces full re-geocode
- [x] Admin-gate Valhalla `force` prepare
- [x] Docker publish Attest skipped on private repos (was failing every CI run)
- [x] gpsd unlock on segment change (no fog holes at speed)
- [x] Kismet REST watermark inclusive-second + future-clock reset
- [x] Drive: Valhalla restart gated; visible routing errors; skip no-op pushFix in follow
- [x] Drive: pause level auto-confirm while moving; Start stays off until route exists
- [x] Host compose loads root `../.env`; default image `wardrivrr-api:local`
- [x] Level-job Valhalla retry no longer `force=True`; docker-run Valhalla binds loopback
- [x] gpsd unlock requires ready level; headless level fallback (`GPSD_LEVEL_ID` / sole ready)
- [x] Localize COALESCE for encryption/channel; status.js escapes fillDl
- [x] Failed region job → level `error` (not stuck processing)
- [x] Mirror `active_level_id` to collection user; clear on delete
- [x] No observation radius unlock on Drive `/roads` poll
- [x] `run.sh` rewrites systemd unit to clone path; gpsd fix script no `-G`
- [x] Parked/idle pause: skip fog unlock, drive XP, and Kismet live inserts unless the receiver moved ≥100 m in 5 min (`GPSD_STATIONARY_*`; flag on `gps_state`)

---

## User tonight (manual / capture)

- [ ] Drop real PNGs into `docs/screenshots/` (`drive`, `regions`, `progress`, `status`, `stats`)
- [ ] Fresh Docker boot: confirm `/setup` → create password → login → Drive
- [ ] Run password reset one-liner against a running `wardrivrr_api` container
- [ ] Confirm `./data` still mounted and survives container recreate (incl. `.jwt_secret`)
- [ ] Vehicle host: `./deploy.sh` once, blank JWT prompt → secret appears under `data/.jwt_secret`
- [ ] Rotate any existing deploy that still has a known-weak `DB_PASS` / old JWT placeholder in `.env`
- [ ] Smoke: create region, Valhalla come-up, gpsd + Kismet chips on Status

---

## Still open (from REVIEW.md)

### Logic

| Sev | Item | Notes |
| --- | --- | --- |
| P2 | Network XP counts imported (WiGLE/backup) data | Design decision |
| P2 | Observation unlock can unlock parallel undriven streets | Build-time only now; not on `/roads` poll |

### Performance

| Sev | Item | Notes |
| --- | --- | --- |
| P1 | Full-region GeoJSON `/roads` payload | Vector tiles / bbox delta |
| P1 | ~6 route scans + 2 `setData` per frame while driving | `navigate.js` |
| P1 | Region build scans regional PBF twice; 4-point clip sampling | `levels.py`, `address_index.py` |
| P2 | No connection pooling | `db.py` — less urgent after tick work cuts |

### Security (remaining)

| Sev | Item | Notes |
| --- | --- | --- |
| P1 | Docker socket still used by normal Valhalla prepare | Needed for Drive; force=admin-only. Proxy / digest pin still open |
| P1 | 30-day tokens, token in `localStorage`, no revocation | Epoch invalidates on process restart; cookie HttpOnly exists |
| P1 | Kismet httpd defaults to `0.0.0.0` | Set `KISMET_HTTPD_BIND=127.0.0.1` to lock down |
| P2 | Geofabrik downloads uncapped; no CSP/SRI; CORS `*` | Various |

### Deployment notes (carry forward)

- Existing PostGIS volumes keep their original `DB_PASS` — rotate with `ALTER USER` + `.env` if still default.
- gpsd: remove `-G` manually on older hosts if present.
- `DB_BIND` / `VALHALLA_BIND` stay localhost unless you intentionally open the LAN.

---

## Do not break

- Brand stickers under `frontend/brand/**/stickers/` stay in the image / tree — never delete.
- Bluey / Winnie the Pooh cuts are user-supplied local assets (not scraped by agents/CI; do not commit scraped Disney art). To restore: drop transparent PNGs or sheets into `frontend/brand/kidcore/` (`s-l1600.jpg` for Bluey; `winnie*` / `pooh*` / `winniethepooh*` for Pooh), then run `python tools/extract_kidcore_stickers.py` and `python tools/prep_kidcore_stickers.py` (ships into `stickers/{bluey,winnie_pooh,random_character,legacy}/` + `stickers.json` packs). Gallery links: `CREDITS.md` (DisneyClips) — respect their / rights-holder terms.
- Docker `./data` (and related) bind mounts stay intact for persistence across recreate.
