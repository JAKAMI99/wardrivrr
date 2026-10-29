#!/usr/bin/env python3
"""
Build / refresh the offline worldwide cities SQLite used by levels place search.

Source: GeoNames cities5000 (CC-BY 4.0) — see thanks.md.
  https://download.geonames.org/export/dump/cities5000.zip

Usage (from repo root):
  python scripts/build_cities_db.py
  python scripts/build_cities_db.py --min-population 5000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from cities_db import GEONAMES_CITIES_URL, build_cities_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build offline worldwide cities.sqlite")
    parser.add_argument("--min-population", type=int, default=5_000)
    parser.add_argument("--url", default=GEONAMES_CITIES_URL)
    args = parser.parse_args()
    path = build_cities_db(
        min_population=args.min_population,
        url=args.url,
        force=True,
    )
    print(f"[cities] ready: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
