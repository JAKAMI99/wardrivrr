# wardrivrr — Fog of War & Wardriving Exploration

> A gamified, open-source, local-first routing and signals-intelligence engine for explorers on foot, by bike, or in any vehicle.

![System Status](https://img.shields.io/badge/System-Online-brightgreen?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Debian%20%2F%20any%20x86__64-orange?style=for-the-badge)

---

## About

wardrivrr turns everyday movement into territorial exploration. Instead of marking a whole street “visited” from a single GPS fix, it can split road networks into precise **35-metre segments** along the direction of travel.

While you move, an optional capture rig records wireless signals (Wi-Fi, Bluetooth LE, and related sources). The backend can map-match positions, clear Fog of War on the map, and (later) suggest unexplored routes. The **mobile-first WebUI** runs in any modern browser — phone, tablet, or laptop — including a device tethered to a local hotspot in a car.

---

## Example hardware (optional)

A typical local-first setup (one example; not required):

* **Compute:** mini-PC or laptop (e.g. AMD Ryzen-class, 16–32 GB RAM).
* **Storage:** SSD for maps, Kismet logs, and PostGIS data.
* **OS:** Debian or similar Linux.
* **Radios:** Wi-Fi adapter with monitor mode, optional BLE dongle, USB GPS via `gpsd`.

You can also run without live capture and **import Kismet databases and/or WiGLE CSVs** after the fact.

---

## Software architecture

```
                  ┌──────────────────────────────────────────┐
                  │   Browser (phone / tablet / laptop)      │
                  └────────────────────┬─────────────────────┘
                                       │ HTTP / WebSockets
                                       ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                            Docker / local stack                         │
 │                                                                         │
 │   ┌───────────────┐     ┌───────────────┐     ┌─────────────────────┐   │
 │   │    Frontend   │◄───►│    Backend    │◄───►│       PostGIS       │   │
 │   │ (WebUI)       │     │   (FastAPI)   │     │ (Spatial Database)  │   │
 │   └───────────────┘     └───────┬───────┘     └─────────────────────┘   │
 │                                 │                                       │
 │                                 ▼                                       │
 │                         ┌───────────────┐                               │
 │                         │    Valhalla   │                               │
 │                         │ (Routing)     │                               │
 │                         └───────────────┘                               │
 │                                 ▲                                       │
 │   ┌───────────────┐             │                                       │
 │   │     Kismet    ├─────────────┘ (optional GPS & RF capture)           │
 │   │ (RF Capturing)│                                                     │
 │   └───────────────┘                                                     │
 └─────────────────────────────────────────────────────────────────────────┘
```

---

## Module docs

### 1. PostGIS (`docs/POSTGIS.md`)
Spatial memory: road segments, signal samples, derived network locations.

### 2. Valhalla (`docs/VALHALLA.md`)
Offline routing with costings that can prefer unexplored roads.

### 3. Kismet (`docs/KISMET.md`)
Optional RF/GPS capture; logs import as `.kismet` / `.kis_db`.

### 4. Backend (`docs/BACKEND.md`)
FastAPI: ingest (Kismet + WiGLE), localization, map APIs, gamification hooks.

### 5. Frontend (`docs/FRONTEND.md`)
Mobile-first WebUI (map, filters, opt-in 3D recalculation).

---

## Motivation

*Built to pull wardriving out of dry CSV dumps and into a playable open-world exploration loop — walk, bike, or drive.*
