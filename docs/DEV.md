# 🛠️ Developer Guide & Quickstart (DEV.md)

Willkommen zurück! Diese Anleitung bringt dich schnell in den Code, ohne dass du lange überlegen musst, wo du aufgehört hast.

---

## 📌 1. Architektur-Prinzip für die Entwicklung
* **Infrastruktur (PostGIS):** Läuft stabil isoliert im **Docker-Container**.
* **Logik & UI (Backend & Frontend):** Laufen **lokal auf dem Host** (ohne Docker-Build-Umwege), damit du dank Hot-Reload sofortiges Feedback und direkten Debugging-Zugriff hast.

---

## 🚀 2. Schnellstart (DB + Web)

Ein Entry-Point startet **PostGIS (Docker)** und den **lokalen FastAPI-Server** (UI inklusive):

```bash
cd /pfad/zu/wardrivrr
python -m venv venv
# Windows:
.\venv\Scripts\pip.exe install -r backend\requirements.txt

# Full mode (default): GPS / Kismet / routing are expected in Status (red if missing)
.\venv\Scripts\python.exe run_dev.py

# Database mode: home-server dashboard — only DB + API; GPS/Kismet/routing show gray (N/A)
.\venv\Scripts\python.exe run_dev.py --database
# alias: --db
```

**Debug in Cursor / VS Code:** F5 → **`wardrivrr: full (API + DB)`** or **`wardrivrr: database mode (API + DB)`**.

Dann im Browser:
* UI Home: http://localhost:8000/
* Database: http://localhost:8000/database
* Settings: http://localhost:8000/settings
* API docs: http://localhost:8000/docs

Manuell getrennt (falls nötig):
```bash
docker compose up postgis -d
cd backend
..\venv\Scripts\uvicorn.exe main:app --reload --port 8000
```

### Schritt 4: Daten importieren (Kismet und/oder WiGLE)
Kopiere Logs nach `data/incoming/` und importiere sie:

```bash
python scripts/ingest.py data/incoming/
```

Unterstützt `.kismet` / `.kis_db` / SQLite (Kismet oder pwnamap) und WiGLE-CSV. Danach läuft automatisch die **2D**-Lokalisation. Optional später:

```bash
python scripts/ingest.py --recompute-only --recompute-3d
```

---

## ⌨️ Wichtige Befehle im Überblick

| Aktion | Befehl |
| :--- | :--- |
| **Full (DB + API)** | `python run_dev.py` oder F5 → `wardrivrr: full` |
| **Database mode** | `python run_dev.py --database` oder F5 → `wardrivrr: database mode` |
| **PostGIS starten** | `docker compose up postgis -d` |
| **PostGIS stoppen** | `docker compose stop postgis` |
| **DB-Shell öffnen** | `docker exec -it wardrivrr_postgis psql -U explorer -d wardriving` |
| **Nur Backend** | `cd backend && uvicorn main:app --reload --port 8000` |

---

## 🤖 Tipp für den Einstieg mit AI / Cursor
Wenn du startest, öffne den Cursor-Composer (`Ctrl + I` / `Cmd + I`) und gib ihm diesen Prompt, um direkt loszulegen:

> *"Lass uns das FastAPI-Backend in `backend/main.py` aufbauen. Es soll Endpunkte für den Geofabrik-Regionen-Index (`/api/regions`) und einen Hintergrund-Task für den PBF-Download und PostGIS-Import bereitstellen. Die Verbindung zur PostGIS-Datenbank läuft über psycopg2."*

Viel Erfolg bei der Umsetzung von wardrivrr! 🚀