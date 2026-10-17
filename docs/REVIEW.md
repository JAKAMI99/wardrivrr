# wardrivrr project review

Review of backend, frontend and deployment on `cursor/fix-drive-xp-kismet-valhalla`,
Oct 17 2026. Findings came from three independent passes; the ones marked
"re-checked" were re-read line by line.

Fix priority used: logic, then performance, then the cheap security wins.

Status legend: **Fixed** (in this branch), **Partial**, **Open**.

## Logic

| Sev | Finding | Where | Status |
| --- | --- | --- | --- |
| P0 | Revisit XP farmed while parked: a held snap re-credited the same segment plus its "ahead" neighbour every 2.5 s (~2,900 XP/h). A segment unlocked as "ahead" counted as a revisit on the next tick. | `levels.py` unlock paths | **Fixed**: a revisit only counts when `last_driven_at` is older than `REVISIT_COOLDOWN_S` (default 30 min). Every pass stamps `last_driven_at`, so parking or the ahead neighbour never re-credits. |
| P1 | Every live recompute overwrote stored addresses with NULL (re-checked). | `localize.py` `UPSERT_SQL` | **Fixed**: `COALESCE(EXCLUDED.x, networks.x)` for the address columns. |
| P1 | Cross-user stats returned on any `TypeError` (re-checked). | `main.py` `stats_dashboard` | **Fixed**: fallback removed. |
| P1 | Achievement toasts were swallowed: background threads (gpsd, Kismet) won the unlock insert, so the UI never saw `newly_unlocked`. | `achievements.py` | **Fixed**: `user_achievements.notified_at` plus `pop_unnotified()`. The Drive HUD toasts every unlock not yet shown, whichever thread made it. Existing unlocks are migrated as already shown. |
| P1 | Parked GPS jitter (and 5 Hz noise) counted as km driven. | `achievements.record_drive_step` | **Fixed**: distance is credited from an anchor once moved ≥ 10 m, and is ignored when the reported speed is < 0.8 m/s. |
| P1 | Drive boot offered a region at the hardcoded default coordinates and auto-accepted after 20 s. | `navigate.js` | **Fixed**: prompts require `state.hasLiveFix` (a real fix or a manual spawn). The first fix retries the prompt. |
| P1 | `navigation_active` set true and never cleared, so geocode stayed throttled forever. | `navigate.js` boot | **Fixed**: cleared on `pagehide` (keepalive), set again on bfcache `pageshow`. |
| P1 | Boot awaited Valhalla prep (up to ~15 min) before GPS follow started. | `navigate.js` boot | **Fixed**: follow starts first; prep runs in the background with the routing banner (no overlay) and concurrent prepares are de-duplicated. |
| P1 | Wrong-way streak counted animation frames, not GPS fixes; replans every 1.5 s aborted each other. | `navigate.js` `checkOffRoute` / `triggerReplan` | **Fixed**: streak counts each fix once (`fixSeq`); no new replan while one is in flight. |
| P1 | Stale fog after a region switch; forced refresh lost behind an in-flight request. | `navigate.js` `refreshFog` | **Fixed**: responses for another region are dropped; forced refreshes are queued; fog refreshes after a switch or a finished build. |
| P1 | Region-create network error left the build overlay stuck; errors went to the hidden `#navHint`. | `navigate.js` `acceptLevelPrompt` | **Fixed**: try/catch hides the overlay; failures show a visible toast. |
| P1 | Rebuilding a region erases fog progress and tile XP. | `levels.py` rebuild path | **Open**: snapshot explored `osm_id`s and re-apply them after the rebuild. |
| P1 | Geocode cache never retries misses; job coalescing widens to "re-geocode everything". | `geocode.py`, `jobs.py` | **Open** |
| P2 | Mute toggle used POST; the backend only accepts PATCH (re-checked). | `navigate.js` | **Fixed** |
| P2 | Drive session window never reset; Wi‑Fi type buckets overwrote each other (`=` instead of `+=`). | `gpsd_poller.py`, `drive_session.py` | **Fixed**: new session after 30 min without fixes (`GPSD_SESSION_IDLE_S`). |
| P2 | Startup try/except hid job-worker start failures. | `main.py` `on_startup` | **Fixed**: bootstrap admin and the worker start separately and log errors. |
| P2 | Network XP counts imported (WiGLE/backup) data. | `achievements.py` | **Open**: design decision. |
| P2 | Observation unlock (Kismet samples within 30 m) can unlock parallel streets that were never driven. | `levels._refresh_explored_from_observations` | **Open**: now runs at most once a minute (see Performance), but the semantics are unchanged. |

## Performance

| Sev | Finding | Where | Status |
| --- | --- | --- | --- |
| P0 | Full achievement evaluation on every 5 Hz GPS tick: DDL twice, a 10-query snapshot including full `signal_samples` altitude scans, and Python regex over all BT/BLE. | `gpsd_poller.py` → `achievements.py` | **Fixed**: schema DDL once per process. Evaluation is throttled to every 15 s per user (`ACH_EVAL_MIN_INTERVAL_S`), shared by gpsd, Kismet and the HUD. A stationary tick does no DB write. Partial indexes back the altitude counts; the two `road_segments` queries are merged. |
| P0 | Drive polled `/api/gps/fix` every 200 ms, and each poll ran session stats, the anomaly GROUP BY and `evaluate_achievements`. | `main.py` `gps_get_fix` | **Fixed**: the HUD extras are cached for 2 s per user and session; position stays at 5 Hz. |
| P0 | Kismet live stored a sample per visible device per 2.5 s poll (~1.7M rows/day parked), positioned at Kismet's running average. | `kismet_live.py` | **Fixed**: per-device thinning keeps a sample only if the observer moved ≥ 20 m, 5 min passed, or the signal improved ≥ 6 dB. The position is the fresh gpsd raw fix (falling back to Kismet `last`/`avg_loc`). Thinned devices still advance the REST watermark. |
| P0 | Blocking work on the async event loop: `.kismet` upload, backup import, and psycopg2 auth on every request. | `main.py`, `auth.py` | **Fixed**: sync handlers and dependencies (threadpool); uploads stream to disk with a `MAX_UPLOAD_MB` cap (default 2048). |
| P1 | gpsd reader backlog: buffered TPVs were applied late and lag compounded. | `gpsd_poller._read_loop` | **Fixed**: drains the socket and applies only the newest TPV. The collection-user lookup is cached (it was one DB connection per tick). |
| P1 | `GET /roads` re-ran the observation unlock (spatial probe per locked segment) every 8 s. | `levels.get_level_road_map` | **Fixed**: at most once a minute per user and region. The full-region GeoJSON payload is still **Open** (vector tiles / bbox delta). |
| P1 | Region-wide explored SUM recomputed on every unlock pass. | `levels.py` | **Fixed**: only when something new was unlocked. |
| P1 | Valhalla restart inside `GET navigate/status` with no lock, so status polls during rm→up started concurrent restarts. | `valhalla_prep.py`, `main.py` | **Fixed**: process-wide RLock; status polls use a non-blocking acquire and report `busy`. |
| P1 | Kismet file fallback re-parsed the whole log every ~12 s while REST was down. | `kismet_live._fallback_kis_db` | **Fixed**: skipped while size and mtime are unchanged. |
| P1 | Drive page rendered at 60 fps when parked in follow mode. | `navigate.js` `wantsFastLoop` | **Fixed**: parked follow ticks at 4 Hz, with full rate while moving or 2 s after. `moving` now uses gpsd speed > 1.5 km/h instead of jitter. |
| P1 | ~6 full route scans plus 2 `setData` calls per frame while driving. | `navigate.js` frame loop | **Open** |
| P1 | Region build scans the regional PBF twice in Python; 4-point clip sampling. | `levels.py`, `address_index.py` | **Open** |
| P2 | Missing indexes; `IS NOT DISTINCT FROM` defeated index use. | schema, `levels.py` | **Fixed**: `(level_id, osm_id)`, `(user_id, network_id, signal DESC)`, `(user_id, seen_at)` and the altitude partial indexes are created `CONCURRENTLY` at startup (`db.ensure_runtime_indexes`); the join uses `=`. |
| P2 | No connection pooling. | `db.py` | **Open**: much less pressing now that per-tick work is gone. |

## Security

| Sev | Finding | Where | Status |
| --- | --- | --- | --- |
| P0 | Broadcast SSIDs rendered as HTML in the Drive anomaly toast (re-checked). | `navigate.js` | **Fixed**: escaped (`escToast` also escapes quotes now). |
| P0 | SSIDs rendered as HTML in Database map popups (re-checked). | `database.js` | **Fixed**: popups are built as DOM nodes with `textContent`. |
| P0 | Login followed `?next=` unvalidated (`javascript:`, open redirect) (re-checked). | `login.html` | **Fixed**: same-origin paths only. |
| P0 | PostGIS published on `0.0.0.0:5432` with the default superuser password (re-checked). | `docker-compose.yml`, `deploy.sh` | **Fixed**: bound to `127.0.0.1` (`DB_BIND` to override); `deploy.sh` generates `DB_PASS` on fresh installs and warns when an existing volume still uses the default. |
| P0 | `admin/admin` bootstrap, no login rate limit, 4-char passwords. | `auth.py` | **Open** |
| P1 | Unauthenticated `/api/system/status` exposed the live GPS position; `/api/health` leaked global counts. | `main.py` | **Fixed**: status requires auth; anonymous health returns liveness only. |
| P1 | gpsd `-G`, Kismet httpd and Valhalla on all interfaces. | `deploy.sh`, `run.sh`, compose | **Fixed** for new deploys: gpsd without `-G`, Kismet `127.0.0.1` (`KISMET_HTTPD_BIND`), Valhalla `127.0.0.1` (`VALHALLA_BIND`). Existing hosts: see deployment notes. |
| P1 | API key name and other `innerHTML` sinks. | `settings.js`, `nav.js`, `regions.js` | **Fixed** |
| P1 | Docker socket (host root) reachable via endpoints any user can call. | `main.py` navigate endpoints | **Open**: admin-gate, socket proxy, pin image digests. |
| P1 | JWT default secret fallback, 30-day tokens, token in localStorage, no revocation. | `auth.py`, `auth.js` | **Open** |
| P2 | Geofabrik downloads uncapped; no CSP/SRI; CORS `*`. | various | **Open** |

Checked and clean: SQL parameterization, subprocess list-args, path traversal
guards, SSRF (download URLs come from the Geofabrik index), per-user filtering
on regions/jobs/keys/networks, bcrypt passwords, hashed API keys.

## Deployment notes for this branch

- **Schema:** applied automatically at API start. `user_achievements.notified_at`
  is added by the achievements schema; the new indexes build `CONCURRENTLY` in
  a background thread, which takes a while on large `signal_samples` but
  doesn't block writes.
- **DB password on the car:** the existing volume still uses the default.
  Rotate it with `ALTER USER explorer PASSWORD '…'`, then set `DB_PASS` in
  `.env`. With the port bound to localhost this is no longer reachable from
  the network.
- **gpsd on existing hosts:** `/etc/default/gpsd` is no longer rewritten by
  `run.sh`. Remove `-G` from `GPSD_OPTIONS` manually and restart gpsd.
- **Kismet on existing hosts:** `deploy/kismet/kismet_site.conf.teslian` still
  binds `0.0.0.0`. Change it to `127.0.0.1` unless the Kismet web UI is used
  from another device.
- **Remote DB/Valhalla access:** set `DB_BIND=0.0.0.0` / `VALHALLA_BIND=0.0.0.0`
  in `.env` if you need it from the LAN.
- **New env knobs:** `REVISIT_COOLDOWN_S`, `ACH_EVAL_MIN_INTERVAL_S`,
  `GPSD_SESSION_IDLE_S`, `KISMET_THIN_MOVE_M`, `KISMET_THIN_MAX_AGE_S`,
  `MAX_UPLOAD_MB`.
