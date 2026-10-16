# 🗄️ Module Documentation: PostGIS Database Service

## 📌 Rolle im System
PostGIS ist das geografische Gedächtnis des gesamten Projekts. Normale Datenbanken können nur Texte und Zahlen vergleichen – PostGIS versteht Raum, Vektoren, Distanzen und Schnittmengen auf der Erdoberfläche. Es sorgt dafür, dass wir in Echtzeit prüfen können, ob sich das Auto auf einem noch unerkundeten Straßenstück befindet.

---

## 📐 Datenmodell & 35m-Segmentierung

Um das "Fog of War"-Prinzip umzusetzen, speichert die Datenbank Straßen nicht als ellenlange Linien (wie in OpenStreetMap üblich), sondern zerscheidet sie via PostGIS-Funktionen in präzise **35-Meter-Abschnitte in Fahrtrichtung**.

### Vollständiges SQL-Schema (`schema.sql`):

```sql
-- Erweiterung für räumliche Operatoren aktivieren
CREATE EXTENSION IF NOT EXISTS postgis;

-- Tabelle für die 35m-Straßensegmente
CREATE TABLE road_segments (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT NOT NULL,
    road_name VARCHAR(255),
    surface_type VARCHAR(50), -- Nur 'asphalt', 'paved' etc.
    geom GEOMETRY(LineString, 4326) NOT NULL,
    is_explored BOOLEAN DEFAULT FALSE,
    explored_at TIMESTAMP WITH TIMEZONE,
    xp_value INT DEFAULT 10
);

-- Räumliche Indizes für Millisekunden-Abfragen erstellen
CREATE INDEX idx_road_segments_geom ON road_segments USING GIST(geom);
CREATE INDEX idx_road_segments_explored ON road_segments(is_explored);

-- Tabelle für georeferenzierte Access Points & Funksignale
CREATE TABLE captured_ap (
    bssid MACADDR PRIMARY KEY,
    ssid VARCHAR(255),
    signal_type VARCHAR(20), -- 'wifi', 'ble', 'cell'
    first_seen TIMESTAMP WITH TIMEZONE,
    last_seen TIMESTAMP WITH TIMEZONE,
    location GEOMETRY(Point, 4326)
);

-- Räumlicher Index für Funksignale
CREATE INDEX idx_captured_ap_location ON captured_ap USING GIST(location);
```

---

## 🛠️ Docker Deployment Config

Der PostGIS-Container läuft isoliert, ist über ein Docker-Volume persistent und stellt die Schnittstelle für das Backend bereit:

```yaml
version: '3.8'

services:
  postgis:
    image: postgis/postgis:15-3.3
    container_name: wardrivrr_postgis
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${DB_NAME:-wardrive}
      POSTGRES_USER: ${DB_USER:-kismet_user}
      POSTGRES_PASSWORD: ${DB_PASS:-secure_password_123}
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./init-scripts:/docker-entrypoint-initdb.d

volumes:
  pgdata:
```

---

## 🔍 Wichtige SQL-Queries für den Betrieb

### 1. Map Matching (35m-Segment freischalten)
Wird vom Backend aufgerufen, sobald Kismet einen neuen GPS-Punkt meldet:

```sql
UPDATE road_segments 
SET is_explored = TRUE, explored_at = NOW() 
WHERE is_explored = FALSE 
  AND ST_DWithin(
      geom::geodetic, 
      ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geodetic, 
      25.0 -- 25 Meter Umkreis-Toleranz für den GPS-Empfang
  );
```

### 2. Gesamten Explorations-Fortschritt abfragen
Ermittelt den aktuellen Prozentwert der freigeschalteten Straßen in der Region:

```sql
SELECT 
    COUNT(*) FILTER (WHERE is_explored = TRUE) AS explored_segments,
    COUNT(*) AS total_segments,
    ROUND((COUNT(*) FILTER (WHERE is_explored = TRUE)::decimal / NULLIF(COUNT(*), 0)) * 100, 2) AS percentage_unlocked
FROM road_segments;
```