# 🎨 Frontend UI/UX Themes & Design System (THEMES.md)

Willkommen zur UI/UX-Spezifikation für das Wardriving- & Exploration-System!
Dieses Dokument beschreibt die Architektur des Theme-Selectors sowie die drei Kern-Themes:
1. 🍼 Kidcore!!! (pacifiers · plushies · plastic toys)
2. 🏎️ Classic Sleek (minimal vehicle / night HUD)
3. 🟢 Hackerboy CRT / Matrix (Cyberpunk / Wardriving Retro)

---

## 🏗️ 1. Theme Selector & System-Architektur

Das Frontend basiert auf einem dynamischen Theme-Engine-System (z. B. via Tailwind CSS / CSS Variables + HTML `data-theme` Attribute).

* **Live Switching:** Themes können ohne Reload der Web-App gewechselt werden.
* **Persistence:** Die Wahl wird lokal im `localStorage` sowie im Profil-Backend gespeichert.
* **Modular Assets:** Jedes Theme überschreibt:
  - Color Palette (CSS-Variablen für Primär-, Sekundär-, BG- und Akzentfarben)
  - Map Tile Layer (Custom Vector Style oder Raster Tiles)
  - UI-Icons (SVG/Pixel-Art Sets)
  - Sound-Effects (Web Audio API / Custom Soundbanks)
  - Custom Cursor & Standort-Marker
  - Animationen & Partikel-Effekte

---

## 🎀 2. Theme 1: Littlespace / Kawaii Kidcore <3 (GameBoy 2000s & Animal Crossing Vibes)

Dieses Theme bildet einen bewussten, humorvollen und extrem süßen Kontrast zur "harten" Wardriving- & Hacking-Infrastruktur. Es verwandelt die Erkundungstour in ein gemütliches Retro-Kinderspiel.

### 🎨 Farbpalette (Pastel & Candy Colors)
* **Background / Base:** `#FFF5F8` (Creamy Soft Pink) / `#E8F0FE` (Soft Pastel Blue)
* **Primary / Accent:** `#FF85A1` (Bubblegum Pink) / `#70D6FF` (Pastel Cyan)
* **Secondary:** `#FFD6A5` (Soft Apricot Yellow) / `#FF9770` (Peach)
* **Text / Outlines:** `#4A3E3D` (Warmes Schokoladenbraun statt hartem Schwarz)
* **GameBoy Teal Accent:** `#00B4D8` (GBC Retro Teal)

### 📍 Custom Standort-Marker (Der Herzchen-Pfeil `<3`)
* **Visual:** Ein abgerundetes, dreidimensional schattiertes **Pastell-Herz (`<3`)**, dessen untere Spitze als präziser Richtungszeiger (Heading/Bearing) fungiert.
* **Animation:**
  - **Pulsieren:** Das Herz "schlägt" sanft im Takt der GPS-Aktualisierungen (BPM koppelt sich an die Fahrgeschwindigkeit).
  - **Schwebe-Effekt:** Sanftes Auf- und Abbewegen (Floating-Bobbing-Effekt).
  - **Trailing:** Hinter dem Herzchen entsteht beim Fahren eine kleine, langsam verblasende Spur aus rosa/gelben Sternchen-Partikeln.

### 🍼 Pacifier (Schnuller) Integration & Gamification
* **Paci-Power-Streak (HUD):**
  - Oben rechts im HUD sitzt eine kleine Schnuller-Anzeige (`🍼`).
  - Wenn der Fahrer eine Serie von ungelernten/neuen Straßen entdeckt, füllt sich der Schnuller mit Glitzer.
  - Aktiviert den **"Paci Multiplier" (1.5x XP)** für neue Straßenabschnitte.
* **Paci Quick-Button:**
  - Der zentrale Floating Action Button (FAB) zum Öffnen des Theme Selectors ist ein glänzender Pixel-Art-Schnuller mit sanfter Shake-Animation bei Interaktion.
* **Badges & Ränge:**
  - Level 1: *"Nuckel-Anfänger"*
  - Level 5: *"Wackelzahn-Explorer"*
  - Level 10: *"Sackgassen-König 🍼"*
  - Level 20: *"Königreich-Kartograf ✨"*

### 🗺️ Karten-Nebel & Straßen-Visualisierung (Fog of War)
* **Unvermessener Nebel:** Ein fluffy, rosafarbener bis fliederfarbener Wolkennebel ("Dream Cloud Fog") bedeckt die Karte.
* **Entdeckte Straßen:** 
  - Befahrene Segmente leuchten in knalligem **GameBoy Color Teal** mit einer dünnen, cremeweißen Kontur.
  - Sackgassen werden mit einem kleinen **Pastell-Lollipop-Icon** oder einem Sternchen am Ende markiert.

### 🔊 Sound-Effects & Audio-Feedback (Chiptune & Animal Crossing)
* **Straßen-Segment entdeckt:** Ein weiches, ploppendes *"Pop!"* (Nintendo-Style).
* **Neue Zone / Ortsteil betreten:** Eine kurze 4-Note Chiptune-Jingle (2000s Handheld-Vibe).
* **Level-Up / Achievement:** Fanfare im Stil von *Animal Crossing* Item-Get.
* **Voice-Feedback (optional):** Niedliches Mumble/Gibberish-Gebrause beim Erreichen von Meilensteinen.

---

## 🏎️ 3. Theme 2: Classic Sleek (minimal night HUD)

Ein professionelles, ablenkungsfreies UI für Nachtfahrten und klare Telemetrie auf dem Handy.

### 🎨 Farbpalette
* **Background:** `#111315` (Deep Charcoal / OLED Black)
* **Primary / Accent:** `#E82127` (Alert Red) / `#00E5FF` (Electric Cyan)
* **Secondary:** `#2C3036` (Slate Grey) / `#8E95A0` (Muted Metallic)
* **Text:** `#F5F6F8` (Pure White)

### 📍 Standorts-Marker & Map
* **Marker:** Minimalistischer, scharfer Pfeil-Pfeil mit rotem Glüh-Ring.
* **Fog of War:** Dunkler, eleganter Vektor-Schatten; aufgedeckte Straßen leuchten neon-blau oder rot.
* **HUD:** Reduzierte Telemetrie-Anzeige (Geschwindigkeit, GPS-Genauigkeit, XP/h, Segment-Counter).

---

## 🟢 4. Theme 3: Hackerboy CRT / Matrix (Wardriving Retro)

Für echte Nächte auf der Jagd nach Access Points und unbekannten Straßen – nostalgischer 80s/90s Cyberpunk-Vibe.

### 🎨 Farbpalette
* **Background:** `#050B05` (CRT Screen Black)
* **Primary / Accent:** `#00FF66` (Phosphor Green) / `#FFB000` (Amber CRT)
* **Text:** Monospace Terminal-Grün (`#33FF33`)

### 📍 Standorts-Marker & UI Features
* **Marker:** Crosshair / Radar-Fadenkreuz mit ASCII-Kompass.
* **Visuals:** Subtile CRT-Scanlines, leuchter Phosphor-Nachleuchteffekt (Glow-Filter), ASCII-Art Status-Overlay.
* **Sound-FX:** Retro Terminal Beeps, Geigermüller-Zähler-Knacken beim Entdecken von Wi-Fi/BLE Signalen.

---

## 🛠️ 5. Zusammenfassung & Next Steps im Frontend

1. **CSS Variables File:** `src/styles/themes.css` definieren.
2. **Theme Context Manager:** React/Vue/Svelte Context zur Verwaltung von `currentTheme` und `soundEnabled`.
3. **Sound-Engine:** Einbettung einer leichtgewichtigen Audio-Klasse (`WebAudioAPI`), um latenzfreie Töne abzuspielen.
