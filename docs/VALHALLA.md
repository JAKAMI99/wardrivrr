# 🧭 Module Documentation: Valhalla Offline Routing Engine

## 📌 Rolle im System

Valhalla ist eine High-Performance Open-Source Routing-Engine (C++), die lokal und offline läuft.

Der entscheidende Vorteil gegenüber anderen Routing-Engines wie OSRM oder GraphHopper ist Valhallas Unterstützung für **dynamische Edge-Costings**. Das bedeutet: Wir können dem Router zur Laufzeit mitteilen, dass er bei der Routenberechnung Straßen bevorzugen soll, deren Status in PostGIS noch auf `is_explored = FALSE` steht. Dadurch leitet dich das System automatisch und gezielt in unerforschte Straßen ("Fog of War") — zu Fuß, per Rad oder im Auto.

## 📂 Daten-Vorbereitung & OSM Extract

Valhalla benötigt aufbereitete Binär-Kacheln (`valhalla_tiles.tar`). Diese werden aus einer OpenStreetMap `.pbf`-Datei generiert. 

Default extract is **Nordrhein-Westfalen** (covers Schwelm / Arnsberg). First `docker compose up valhalla` downloads the PBF and builds tiles — that can take a long while.

Host API talks to Valhalla at `VALHALLA_URL` (default `http://127.0.0.1:8002`).

## 🛠️ Docker Deployment Config

Defined in root `docker-compose.yml` (`wardrivrr_valhalla`). Equivalent:

```yaml
services:
  valhalla:
    image: ghcr.io/gis-ops/docker-valhalla/valhalla:latest
    container_name: wardrivrr_valhalla
    restart: unless-stopped
    ports:
      - "8002:8002"
    environment:
      tile_urls: https://download.geofabrik.de/europe/germany/nordrhein-westfalen-latest.osm.pbf
      build_elevation: "False"
      build_admins: "True"
      build_time_zones: "False"
    volumes:
      - valhalla_data:/custom_files

volumes:
  valhalla_data:
```

## 🔌 API Interaction Example

Beispiel für einen POST-Request des Backends an den lokalen Valhalla-Container (`http://valhalla:8002/route`), um eine Turn-by-Turn-Navigation zu berechnen:

```json
{
  "locations": [
    {"lat": 52.5200, "lon": 13.4050, "type": "break"},
    {"lat": 52.5219, "lon": 13.4132, "type": "break"}
  ],
  "costing": "auto",
  "directions_options": {
    "units": "kilometers",
    "language": "de-DE"
  }
}
```