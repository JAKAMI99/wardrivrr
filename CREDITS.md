# Credits

This project would not be possible without the people and organisations who publish open geographic data and keep the infrastructure behind it running.

## OpenStreetMap

© OpenStreetMap contributors. Road and place data that power map packs and routing come from OpenStreetMap.

- https://www.openstreetmap.org/
- Donate: https://donate.openstreetmap.org/

## Geofabrik

Free regional OpenStreetMap extracts (`.osm.pbf`) and the public extract index that lets us resolve which dataset covers a city.

- https://www.geofabrik.de/
- Downloads: https://download.geofabrik.de/

## GeoNames

The worldwide gazetteer and postal-code data used for offline city search and local address / ZIP lookup.

- https://www.geonames.org/
- Support: donations@geonames.org · https://www.geonames.org/donations.html

## Overpass API

Exact city (and city-part) outlines for the levels map come from OpenStreetMap via public Overpass endpoints, when they are reachable. Luckily this is optional :) — without Overpass you can still create levels; roads then use the map-pack area instead of a precise municipal polygon.

- https://overpass-api.de/
- https://wiki.openstreetmap.org/wiki/Overpass_API

## Mapbox GL Directions (maneuver icons)

Turn / roundabout / arrive glyphs in the Drive HUD are vendored from
`@mapbox/mapbox-gl-directions` (`src/icons/`), ISC license.

- https://github.com/mapbox/mapbox-gl-directions

## IEEE Registration Authority (MAC / OUI)

Public MA-L / MA-M / MA-S assignment lists used to resolve Wi‑Fi / Bluetooth
BSSID prefixes to an organization name (vendor). Downloaded at setup into
`data/oui/oui.sqlite` (and refreshed on first API start if missing).

IEEE is the authoritative registrar for these assignments — not a third-party scrape.

- https://standards-oui.ieee.org/
- CSV registries: `oui/oui.csv`, `oui28/mam.csv`, `oui36/oui36.csv`

## Prism Launcher — Cute Engwish (en@uwu)

Kidcore UI speech is inspired by Prism Launcher’s “Cute Engwish” language pack
and the OwOify baseline their translators use. Not vendored runtime code — tone
and transform ideas only.

- Prism Launcher: https://prismlauncher.org/
- Translations (`en@uwu.ts`): https://github.com/PrismLauncher/Translations
- Weblate: https://hosted.weblate.org/projects/prismlauncher/launcher/en@uwu/
- OwOify baseline: https://github.com/aqua-lzma/OwOify

---

When new upstream data providers are added, credit them here and link a donate or support page if one exists.
