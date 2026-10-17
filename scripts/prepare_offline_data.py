#!/usr/bin/env python3
"""
Download / build all offline geographic databases used by wardrivrr.

Run once at setup (or during Docker image/volume prepare). Does **not** start
PostGIS, routing, or Kismet — those stay in their own containers.

What this prepares:
  data/cities/cities.sqlite       — worldwide city search (GeoNames)
  data/geocode/postal.sqlite        — postal / reverse locality (GeoNames)
  data/oui/oui.sqlite             — IEEE MAC / OUI vendor prefixes
  data/geofabrik-index-v1.json    — which OSM extract covers a city

Usage (repo root):
  python scripts/prepare_offline_data.py
  python scripts/prepare_offline_data.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare offline geo data for wardrivrr")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even if databases already exist",
    )
    args = parser.parse_args()

    print("[prepare] cities database…")
    from cities_db import build_cities_db, db_available

    build_cities_db(force=args.force)
    print(f"[prepare] cities ok={db_available()}")

    print("[prepare] postal / reverse-geocode database…")
    from local_geocode import build_postal_db, postal_db_available

    build_postal_db(force=args.force)
    print(f"[prepare] postal ok={postal_db_available()}")

    print("[prepare] Geofabrik extract index…")
    from geofabrik import ensure_index

    n = ensure_index()
    print(f"[prepare] geofabrik extracts={n}")

    print("[prepare] IEEE OUI / MAC vendor database…")
    from oui import build_oui_db, db_available as oui_available

    build_oui_db(force=args.force)
    print(f"[prepare] oui ok={oui_available()}")

    print("[prepare] done — see thanks.md for attribution")
    return 0


if __name__ == "__main__":
    sys.exit(main())
