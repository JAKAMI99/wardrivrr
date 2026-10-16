# 🤖 AI Engineering & Collaboration Guide (`AI.md`)

Willkommen im Leitfaden für KI-gestützte Entwicklung. Dieses Dokument dient als Referenz und Kompass, um komplexe Systemarchitekturen (PostGIS, FastAPI, Leaflet, Docker, Valhalla) mit Hilfe von KI-Agenten und Large Language Models (LLMs) effizient, kostenschonend und ohne Kontrollverlust umzusetzen.

---

## 1. ELI5: Die Rolle des Entwicklers als Architekt & Dirigent

### Was bedeutet "Vibe Coding" wirklich?
Der Begriff *Vibe Coding* wird oft missverstanden als *„Ich tippe Wünsche ein und die KI baut zauberhaft eine fertige App“*. In der Praxis führt dieses blinde Vertrauen schnell zu **Code-Spaghetti**, unentdeckten Sicherheitslücken, Architektur-Müll und massiven Kosten.

In diesem Projekt bist du **kein Passagier**, sondern der **Chief Architect & Dirigent**:

```
 ┌─────────────────────────────────────────────────────────┐
 │               DU (Der Architekt & Dirigent)             │
 │  - Systemarchitektur & Datenfluss (IDEA.md, DEV.md)      │
 │  - Strategische Entscheidungen (PostGIS vs. Memory DB)  │
 │  - Prompting, Review & Qualitätskontrolle               │
 └───────────────────────────┬─────────────────────────────┘
                             │
                             ▼
 ┌─────────────────────────────────────────────────────────┐
 │                 KI-AGENT / EDITOR (Cursor)              │
 │  - Syntax-Generierung & Boilerplate                     │
 │  - Refactoring & Datei-Operationen                       │
 │  - Ausführen von Terminal-Befehlen                      │
 └─────────────────────────────────────────────────────────┘
```

* **Die KI ist der Juniorentwickler:** Sie besitzt unendliches Wissen über Syntax, Bibliotheken und APIs, hat aber kein globales Verständnis für deine Gesamtarchitektur, deine Ordnerstruktur oder deinen Projektkontext.
* **Du gibst den Takt an:** Du zerlegst große Probleme in kleine, funktionale Blöcke, überprüfst den generierten Code kritisch und triffst die architektonischen Richtungsentscheidungen.

---

## 2. Editor-Vergleich: Warum Cursor?

Die Wahl des richtigen IDE-Setups bestimmt, wie flüssig du zwischen Idee und funktionierendem Code wechselst.

| Editor / Tool | Konzept | Vorteile | Nachteile | Eignung für 6-Stunden-Sessions |
| :--- | :--- | :--- | :--- | :--- |
| **Cursor** *(Empfohlen)* | VS Code Fork mit nativer Agenten- & Composer-Integration | • **Composer-Modus:** Ändert mehrere Dateien gleichzeitig.<br>• Native `@`-Referenzierung von Dateien, Ordnern & Docs.<br>• Extrem flüssiges Autocomplete (Tab-Engine). | • Kann bei unbedachtem Composer-Einsatz viele Credits verbrauchen.<br>• Closed-Source-Infrastruktur. | **Sehr hoch** (Bietet die beste Balance aus Multi-File-Edits und Kontrolle). |
| **Windsurf** (Codeium) | VS Code Fork mit "Cascade" Flow | • Sehr gute visuelle Nachverfolgung der KI-Aktionen.<br>• Oft etwas transparenterer Umgang mit Kontext.<br>• Gute Multi-File-Fähigkeiten. | • Composer-Äquivalent fühlt sich bei sehr großen Refactorings teils langsamer an. | **Hoch** (Starke Alternative zu Cursor). |
| **GitHub Copilot** | Extension für VS Code / JetBrains | • Nahtlos integriert.<br>• Günstig ($10/Monat). | • Schlechtere Multi-File-Agenten-Fähigkeiten.<br>• Oft auf kleinere Code-Ausschnitte beschränkt. | **Mittel** (Gut für Autocomplete, schwach für komplexe Architektur-Agenten). |
| **Aider** | CLI-basierter Git-Agent im Terminal | • Arbeitet direkt auf Git-Commits.<br>• Extrem sparsamer Umgang mit Tokens.<br>• Transparenter Open-Source-Ansatz. | • Keine visuelle IDE-Integration.<br>• Reines Terminal-Handling setzt hohe Git-Disziplin voraus. | **Hoch für Profis** (Ideal für Terminal-Enthusiasten, weniger für UI-Entwicklung). |

### Warum Cursor für dieses Projekt?
1. **Multi-File Context:** Unser Stack besteht aus verschachtelten Dateien (`backend/main.py`, `backend/importer.py`, `database/init/01_schema.sql`). Cursor versteht diese Zusammenhänge nativ über das `@`-Symbol.
2. **Composer-Modus:** Wenn der Geofabrik-Importer sowohl die FastAPI-Route als auch den Hintergrund-Task in einer separaten Datei anpassen muss, erledigt Cursor das in einem einzigen Durchgang.

---

## 3. Modell-Vergleich: Welches LLM für welche Aufgabe?

Nicht jedes Modell eignet sich für jeden Task. Wer durchgehend das teuerste Reasoning-Modell nutzt, verbrennt unnötig Budget.

```
       [KOMPLEXITÄT DER AUFGABE]
                 │
                 ├── High-Level Architektur & Logic ──► Claude 3.5 Sonnet / o1
                 ├── SQL / Spatial PostGIS Queries   ──► Claude 3.5 Sonnet
                 ├── FastAPI / Standard Python CRUD ──► GPT-4o / Claude 3.5 Sonnet
                 └── React / Leaflet UI-Component ──► Claude 3.5 Sonnet
```

### Deep-Dive in die Modelle:

#### 🟢 Claude 3.5 Sonnet (Der Allrounder & Standard)
* **Stärken:** Unangefochtener König für Code-Logik, Refactoring, Python, SQL und TypeScript. Erkennt logische Fehler in PostGIS-Queries (z. B. falsche Koordinatensysteme/EPSG) extrem zuverlässig.
* **Einsatzbereich:** 80% deiner gesamten Entwicklungszeit.

#### 🟡 OpenAI o1 / o3-mini (Die "Reasoning" Denker)
* **Stärken:** Bedenkt komplexe mathematische oder architektonische Probleme schrittweise (Deep Reasoning).
* **Einsatzbereich:** Komplexe Geometrie-Prozeduren (z.B. der mathematische Algorithmus zur 35m-Segmentierung unter Vermeidung von Topologie-Brüchen) oder knifflige Bugs, an denen Sonnet scheitert.

#### 🔵 GPT-4o
* **Stärken:** Schnell, gut bei Standard-Python-Syntax, REST-APIs, Shell-Skripten und allgemeinen Fragen.
* **Einsatzbereich:** Schnelle Einzelfragen, Dokumentation schreiben, einfache CRUD-Endpunkte.

#### 🟣 DeepSeek-Coder-V2 / DeepSeek-R1
* **Stärken:** Sehr stark in logischer Code-Generierung zu extrem geringen Kosten.
* **Einsatzbereich:** Hervorragendes Fallback-Modell bei langen Nächten, um das primäre Guthaben zu schonen.

---

## 4. Token-Ökonomie & Cost Management

Wenn du in eine 6-stündige Nachteule-Session eintauchst, musst du verhindern, dass der Kontext-Fenster-Speicher überquillt und dein Guthaben vernichtet wird.

### 💰 Wie Kosten & Tokens entstehen
Jeder Prompt an die KI überträgt nicht nur deine neue Frage, sondern **den gesamten bisherigen Chat-Verlauf** sowie alle per `@` angehängten Dateien.
* **Langer Chat (50 Nachrichten) + 5 angehängte Dateien = Riesiger Token-Verbrauch pro Nachricht.**

### 🛡️ Die 4 Regeln der Token-Hygiene

1. **Neuer Chat pro Feature (Chat-Refresh):**
   * Diskutiere den Geofabrik-Importer in Chat A.
   * Wenn der Importer läuft und du zum Frontend wechselst: **Schließe Chat A und öffne Chat B.**
   * *Vorteil:* Chat B startet sauber, verbraucht nur einen Bruchteil der Tokens und halluziniert keine alten Themen hinein.

2. **Gezielte `@`-Referenzierung:**
   * **DON'T:** `@Codebase` (Zwingt die KI, das gesamte Projekt einzulesen – extrem teuer).
   * **DO:** Gezielt nur die relevanten Dateien anhängen: `@backend/main.py` `@backend/importer.py`.

3. **Composer vs. Chat unterscheiden:**
   * **Chat (`Ctrl + L` / `Cmd + L`):** Für Erklärungen, Fehlersuche, Konzeptfragen und kurze Code-Schnipsel.
   * **Composer (`Ctrl + I` / `Cmd + I`):** Erst verwenden, wenn klar ist, *was* gebaut werden soll und konkrete Schreiboperationen in Dateien anstehen.

4. **Kontext schlank halten mit Dokumenten:**
   * Anstatt der KI in 10 Prompts deine Idee zu erklären, hänge einfach `@IDEA.md` oder `@DEV.md` an den ersten Prompt an.

---

## 5. DOs und DON'Ts für "Vibe Coder" / AI-Piloten

### ✅ DOs (Best Practices)
* **Divide and Conquer:** Zerlege Aufgaben in isolierte Teilschritte (z. B. erst PBF-Download, dann `osm2pgsql`-Aufruf, dann PostGIS-Trigger).
* **Code-Review vor Akzeptanz:** Lies den Diff (die roten/grünen Zeilen im Composer) aufmerksam durch, bevor du auf *Accept* klickst.
* **Fehlermeldungen 1:1 reinwerfen:** Kopiere den exakten Stacktrace aus dem Terminal inklusive Zeilennummern in den Chat.
* **Den "Erklär-Trick" nutzen:** Frage regelmäßig: *„Erkläre mir in 2 Sätzen, warum du Funktion X so umgeschrieben hast.“*

### ❌ DON'Ts (Anti-Pattern)
* **Der Megaprompt:** *"Baue mir das komplette System inklusive Datenbank, FastAPI, Docker und WebUI."* ➔ führt garantiert zu fehlerhaftem Code.
* **Blinder Akzeptanz-Rausch:** 10 Composer-Vorschläge hintereinander akzeptieren, ohne dazwischen den Code auszuführen oder zu testen.
* **Geister-Bugs jagen:** Stundenlang KI-Prompts gegen einen Fehler werfen, obwohl die Ursache ein nicht gestarteter Docker-Container oder ein Tippfehler in der `.env`-Datei ist.
* **Kontext-Verschmutzung:** Im selben Chat über PostGIS-Indizes, React-CSS-Styles und Docker-Build-Fehler diskutieren.

---

## 6. TODOs & Checkliste für den Einstieg

Bevor du mit dem Coden startest, arbeite diese Checkliste ab:

### 📋 Start-Checkliste
- [ ] **Projekteinstellungen prüfen:**
  - [ ] Projektordner in Cursor geöffnet (`cursor .`).
  - [ ] `.gitignore` erstellt (damit `venv`, `pgdata` und `.pbf`-Dateien nicht im Git landen).
- [ ] **Infrastruktur prüfen:**
  - [ ] PostGIS-Container via Terminal gestartet: `docker compose up postgis -d`.
  - [ ] Verbindung zur DB getestet: `docker exec -it wardrivrr_postgis psql -U explorer -d wardriving`.
- [ ] **Erster KI-Prompt (im neuen Chat):**
  - [ ] Öffne Cursor Chat (`Ctrl + L`).
  - [ ] Füttere die KI mit Kontext: `@DEV.md` `@IDEA.md`.
  - [ ] **Prompt:**
    > *"Ich möchte das FastAPI-Backend für den Geofabrik-Importer aufbauen. Lass uns Schritt 1 umsetzen: Eine Funktion in `backend/importer.py`, die die `index-v1.json` von Geofabrik abruft und als strukturiertes JSON zurückgibt. Erstelle zuerst nur das Skript und erkläre mir kurz den Ablauf."*

---
*Mit diesem Leitfaden hast du die volle Kontrolle über dein Projekt. Baue Schritt für Schritt, bleibe der Architekt und lass die KI die schwere Tipparbeit erledigen!*