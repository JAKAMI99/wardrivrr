# ⚡ Module Documentation: FastAPI Python Core Backend

## 📌 Rolle im System

Das Backend ist das schlagende Herz und die zentrale Steuerungszentrale des gesamten Projekts. Es ist als hochperformante **FastAPI (Python)** Applikation konzipiert und koordiniert alle Services: Es nimmt Sensordaten entgegen, füttert die PostGIS-Datenbank, spricht mit Valhalla, berechnet XP und Level, überwacht die Container und stellt APIs für das Frontend sowie zukünftige Clients (Android App, externe Tools) bereit.

---

## 🏗️ Architektur & Kernaufgaben

1. **Ingestion & Map-Matching Engine:** 
   * Verarbeitet hochladbare Kismet-Daten (`.kismet` / `.kis_db`) oder direkte Echtzeit-Websocket-Streams.
   * Übersetzt GPS-Koordinaten in räumliche Operationen und schaltet 35-Meter-Straßensegmente in PostGIS frei.
2. **Gamification & Levelsystem:**
   * Berechnet XP pro freigeschaltetem Straßensegment, geparstem WLAN und entdecktem Bluetooth-Beacon.
   * Dynamische Level-Berechnung (z.B. exponentielle XP-Kurve) und Achievement-Prüfung (z.B. *"Berlin Complete"*).
3. **Multi-Client API Gateway:**
   * **WebUI API:** Versorgt das mobile Frontend mit GeoJSON, HUD-Daten und Routen.
   * **Android / Mobile API:** Authentifizierte Endpunkte für eine zukünftige Companion-App.
   * **Public / Inter-Project API:** Sichere Endpunkte zum Abfragen gescannter Netzwerke (für andere Open-Source-Projekte).
4. **Service & Container Supervisor:**
   * Überwacht via Docker API (`/var/run/docker.sock`), ob Kismet, PostGIS und Valhalla fehlerfrei laufen und meldet Ausfälle.
5. **User Authentication & Security:**
   * JWT-basierte Authentifizierung (JSON Web Tokens), um sensible Endpunkte und den Upload-Bereich vor unbefugtem Zugriff im öffentlichen WLAN zu schützen.

---

## 🛠️ Docker Deployment Config

```yaml
services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: wardrivrr_backend
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - DB_HOST=postgis
      - DB_PORT=5432
      - DB_NAME=${DB_NAME:-wardrive}
      - DB_USER=${DB_USER:-kismet_user}
      - DB_PASS=${DB_PASS:-secure_password_123}
      - VALHALLA_URL=http://valhalla:8002
      - JWT_SECRET_KEY=super_secret_change_me_in_production
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - kismet_logs:/app/logs:ro
    depends_on:
      - postgis
      - valhalla

volumes:
  kismet_logs:
```

---

## 🔌 API-Endpunkte Übersicht (FastAPI Router)

### 🗺️ Map & Exploration
* `GET /api/v1/map/segments` — Liefert Straßensegmente als GeoJSON (gefiltert nach Bounding Box und `is_explored`).
* `POST /api/v1/map/route` — Fordert eine Entdeckungs-Route von Valhalla an (bevorzugt unerkundete Straßen).

### 📡 Data Ingestion & Localization
* CLI: `python scripts/ingest.py` — importiert Kismet-DBs und/oder WiGLE-CSVs in `signal_samples`, danach 2D-Recompute.
* `POST /api/localize/recompute` — Opt-in (z. B. `{ "mode": "3d" }`); Standard-Ingest bleibt 2D.
* `GET` / `PATCH /api/settings` — u. a. `default_localization_mode`.
* `WS /api/v1/ingest/live` — WebSocket für Live-Stream (geplant).

### 🎮 Gamification & User Stats
* `GET /api/v1/user/stats` — Gibt aktuelle XP, Level, Fortschrittsleiste (%) und gefahrene Meter zurück.
* `GET /api/v1/user/achievements` — Liste freigeschalteter und offener Badges.

### 🛡️ System & Container Monitoring
* `GET /api/v1/system/health` — Prüft den Status von PostGIS, Valhalla und Kismet (inkl. Docker-Container-Metriken).

### 🔑 Authentication
* `POST /api/v1/auth/login` — Generiert ein JWT-Token für geschützte API-Calls.