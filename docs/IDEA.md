# Vision, Concept & Architecture (`IDEA.md`)

## 1. Vision: open-world exploration in real life

Classic wardriving tools (Kismet, WiGLE clients, GIS dumps) are technical and export-oriented. **wardrivrr** turns movement into a physical open-world exploration loop — on foot, by bicycle, or in any vehicle:

* **Fog of War:** the map starts veiled; segments you actually travel light up.
* **No fixed destination (infinite explorer):** optional routing pulls you toward unexplored areas instead of only A→B navigation.
* **Optional capture rig:** USB GPS, `gpsd`, and Kismet (Wi-Fi / BLE) run independently of any vehicle brand API. You can also import logs later.

---

## 2. Infinite explorer (moving horizon)

1. Live GPS (or imported tracks) feeds the backend.
2. PostGIS finds nearby unexplored 35 m segments.
3. Valhalla gets dynamic waypoints through unexplored clusters.
4. If you leave the suggested path, the horizon re-plans.

---

## 3. Dead-end protection

* Topology tagging: degree-1 edges marked `is_dead_end`.
* Smart-bundle: include nearby dead-ends early when the route already passes their entrance.
* Profile-weighted turn penalty (car vs bike vs foot).

---

## 4. Travel profiles

| Profile | Valhalla costing | Dead-end handling | Use |
| :--- | :--- | :--- | :--- |
| **Car (default)** | `auto` | Smart-bundle / low frustration | Roads, industrial, rural |
| **Bicycle** | `bicycle` | High density | Paths, gravel, side roads |
| **Pedestrian** | `pedestrian` | Full coverage | Footways, parks, alleys |

---

## 5. District progress (OSM admins)

Segments joined to admin polygons (`admin_level` 6 / 8 / 10) for per-district unlock %.

---

## 6. Roadmap

### Phase 1: Core & local data (current)
- [ ] Docker/local PostGIS + FastAPI + mobile WebUI
- [ ] Dual ingest: Kismet DB + WiGLE CSV → raw samples + derived locations
- [ ] Default 2D localization; opt-in 3D recalculation
- [ ] 35 m segmentation & Fog of War (next)

### Phase 2: Infinite loop & audio HUD
- [ ] Dynamic exploration routing API
- [ ] Web Audio unlock / level-up cues

### Phase 3: Multi-client & sync
- [ ] Optional encrypted home sync
- [ ] Companion-friendly mobile WebUI (PWA later)
- [ ] WiGLE.net export when on home Wi-Fi

### Phase 4: Analysis
- [ ] Rogue AP warnings
- [ ] Live density heatmaps

---

## 7. Privacy, safety & ethics

1. **Passive scans only** via Kismet — no deauth / active attacks.
2. **Mobile-first, low-distraction UI** — usable on a phone mount; keep attention on traffic when moving.
3. **Local first** — positions, SSIDs, and progress stay on your machine by default.
