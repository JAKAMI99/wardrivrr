# Triangulated network API

WiGLE-style search over your localized `networks` table. Auth with JWT (WebUI) or API key (`wr_…`).

## Interactive docs

- WebUI explorer: [`/api`](/api) — form + curl + results  
- OpenAPI / Swagger: [`/api/docs`](/api/docs)  
- ReDoc: [`/api/redoc`](/api/redoc)

Create a key under **Settings**.

## Auth

```bash
curl -s -H "X-API-Key: wr_…" "http://localhost:8000/api/v2/network/search?ssid=Guest"
# or
curl -s -H "Authorization: Bearer wr_…" "..."
```

## Search

`GET /api/v2/network/search`

| Param | Purpose |
| --- | --- |
| `ssid` | Substring match on name (use `ssid_exact=true` for exact) |
| `mac` / `netid` | MAC/BSSID; separators ignored; prefix OK |
| `place` | Geocode place → bbox (e.g. `Berlin`) |
| `postalcode` / `zip` | ZIP filter (e.g. `10115`), optional `country=de` |
| `type` | `WIFI` \| `BT` \| `BLE` |
| `bbox` | `west,south,east,north` |
| `latrange1/2`, `longrange1/2` | WiGLE-style bounds |
| `near` | `lat,lon` + `radius_m` (default 500) |
| `searchAfter` | Cursor from previous response |
| `limit` | 1–1000 (default 100) |
| `reverse` | Live reverse-geocode if address not stored yet |
| `city` / `address` | Filter stored address fields (filled during localization) |
| `max_accuracy_m` | Only hits with `location_accuracy_m` ≤ this |

### Stored after localization

Each network gets: `address`, `city`, `postcode`, `country`, `location_accuracy_m` (estimated ± meters), `avg_gps_accuracy_m`.

Localization weights samples by **RSSI × GPS accuracy** (tighter GPS fixes count more). Missing GPS accuracy uses a 15 m default.

### Examples

SSID in Berlin:

```bash
curl -s -H "X-API-Key: wr_…" \
  "http://localhost:8000/api/v2/network/search?ssid=XY&place=Berlin&country=de"
```

MAC prefix in ZIP 10115:

```bash
curl -s -H "X-API-Key: wr_…" \
  "http://localhost:8000/api/v2/network/search?mac=AA:BB:CC&postalcode=10115&country=de"
```

Near a point:

```bash
curl -s -H "X-API-Key: wr_…" \
  "http://localhost:8000/api/v2/network/search?near=52.520,13.405&radius_m=800&type=WIFI"
```

## Detail / GeoJSON / geocode

- `GET /api/v2/network/detail?netid=…&include_samples=true` — one network + optional sample summary + reverse geocode  
- `GET /api/v2/network/geojson?…` — same filters as search, FeatureCollection  
- `GET /api/v2/geocode?place=Berlin` or `?postalcode=10115&country=de`  
- `GET /api/v2/geocode/reverse?lat=…&lon=…`  
- `GET /api/v2/stats` — counts for your tenant  

Place/ZIP/reverse geocoding is **fully local**:

- Street + house number: OSM `addr:*` packs built per **generated level** (`data/users/…/levels/…/addresses.sqlite`) — rebuild with `python scripts/build_level_addresses.py --user-id N --level-id M`
- City / ZIP fallback: GeoNames cities + postal DBs (`scripts/prepare_offline_data.py`) plus municipal outlines from `admin_areas`

Attribution: [thanks.md](../thanks.md). Place/ZIP filters expand to a bounding box before querying PostGIS.
