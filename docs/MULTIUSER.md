# Multi-user, levels, backups, localization jobs

## Auth (invite-only)

- First start creates bootstrap admin: `admin` / `admin` (change immediately).
- JWT sessions for the WebUI (`Authorization: Bearer <token>`).
- Admins invite users via Settings → Admin.
- Open registration is intentionally not enabled.

## API keys & ingest

- Settings → create API key (`wr_…`, shown once).
- Header: `X-API-Key: wr_…` or `Authorization: Bearer wr_…`
- Upload: `POST /api/v1/ingest/upload` (multipart file) → stored under `data/users/{id}/incoming/`, ingested into that user’s samples.

## Export / import

Kinds: `user_calculated` (default), `full`, `calculated_only`, `raw_only`.  
Import supports `merge` or `replace`.

## Levels (Geofabrik)

- `/levels` wizard: search **places** (e.g. Berlin, Germany) → map preview → mode → confirm download size → staged progress (download / roads) with ETA.
- City browsing uses a **worldwide** GeoNames SQLite (`data/cities/cities.sqlite`). Offline data is prepared with `python scripts/prepare_offline_data.py` or `docker/prepare-data` (also ensured on startup). See [thanks.md](../thanks.md).
- Selecting a place loads the **exact OSM administrative boundary** (Overpass, disk-cached under `data/cities/boundaries/`) for the map preview and road clip — not a circle.
- Geofabrik extract is resolved in the background (user never picks “Regierungsbezirk …”).
- API: `GET /api/levels/places/search?q=…`, `GET /api/levels/places/boundary?…`
- Schema migration: `scripts/migrate_multiuser_levels.sql` (also in `postgis/init/02_multiuser_levels.sql` for fresh volumes).

## Localization jobs

- Presets: `fast` | `balanced` | `precise` (sample caps).
- Weights: **RSSI × GPS accuracy** (capture `accuracy` meters); estimate stored as `location_accuracy_m`.
- On process / import: triangulate positions first (map-ready), then queue a **geocode** job for addresses.
- Level build also writes a local **OSM address pack** (street/housenumber for that level only). Existing levels: `python scripts/build_level_addresses.py --user-id N --level-id M`
- Geocode uses all logical CPU threads when idle; when `navigation_active` is set (`PUT /api/navigation/active`), it runs fewer workers at low thread priority.
- Bulk backfill: `python scripts/geocode_all_networks.py` (or `--only-missing`)
- Settings: default precision, nightly queue, “Run full calculation now”.
- `POST /api/localize/recompute` with `async_job: true` enqueues a DB-backed job.
- Schema: `scripts/migrate_network_address.sql`

## Triangulated DB API

See [API.md](API.md): `/api/v2/network/search` (MAC, SSID, place, ZIP), `/api` WebUI, `/api/docs` Swagger.

## Deferred (not in this sprint)

- Valhalla turn-by-turn UI
- Headless edge package
- Open registration
- True RF multilateration beyond weighted/search presets
