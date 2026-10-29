#!/usr/bin/env python3
"""
Index city + district outlines (OSM admin boundaries) from a Geofabrik extract
into data/cities/admin_areas.sqlite. The levels wizard reads only this file.

Usage (from repo root):
  python scripts/build_admin_areas.py --city Wuppertal
  python scripts/build_admin_areas.py --extract europe/germany/nordrhein-westfalen/duesseldorf-regbez
  python scripts/build_admin_areas.py --pbf path/to/file.osm.pbf --extract my-region
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from admin_areas import index_pbf  # noqa: E402
from geofabrik import download_pbf, resolve_feature, resolve_place_extract  # noqa: E402

PBF_DIR = ROOT / "data" / "pbf"


def _extract_for_city(name: str) -> str:
    from cities_db import search_cities

    hits = search_cities(name, limit=1, min_population=0)
    if not hits:
        raise SystemExit(f"City not found in cities DB: {name}")
    h = hits[0]
    ext = resolve_place_extract(
        h["lat"],
        h["lon"],
        place_bbox=h["bbox"],
        country_code=h.get("country_code"),
        country_name=h.get("country"),
        place_name=h.get("name"),
    )
    if not ext:
        raise SystemExit(f"No Geofabrik extract covers {h['label']}")
    print(f"{h['label']} -> {ext['id']}")
    return ext["id"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local city/district outline index")
    parser.add_argument("--city", help="Resolve the covering Geofabrik extract from a city name")
    parser.add_argument("--extract", help="Geofabrik extract id")
    parser.add_argument("--pbf", type=Path, help="Use an existing .osm.pbf instead of downloading")
    parser.add_argument(
        "--delete-pbf",
        action="store_true",
        help="Delete the PBF after indexing (default: keep under data/pbf/)",
    )
    args = parser.parse_args()

    extract_id = args.extract or (_extract_for_city(args.city) if args.city else None)
    if not extract_id:
        parser.error("give --city or --extract")

    pbf = args.pbf
    downloaded = False
    if not pbf:
        feat = resolve_feature(extract_id)
        if not feat or not feat.get("pbf_url"):
            raise SystemExit(f"Unknown Geofabrik extract: {extract_id}")
        pbf = PBF_DIR / (extract_id.replace("/", "_") + ".osm.pbf")
        if not pbf.exists():
            print(f"Downloading {feat['pbf_url']} …")
            last_mb = -1

            def on_progress(frac, done, total):
                nonlocal last_mb
                mb = int((done or 0) / 1048576)
                if mb == last_mb:
                    return
                last_mb = mb
                print(f"\r  {mb} MB ({frac * 100:.0f}%)", end="", flush=True)

            download_pbf(feat["pbf_url"], pbf, progress_cb=on_progress)
            print()
            downloaded = True

    print(f"Indexing admin boundaries from {pbf} …")
    index_pbf(pbf, extract_id)
    if downloaded and args.delete_pbf:
        pbf.unlink(missing_ok=True)
    elif downloaded:
        print(f"Kept PBF at {pbf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
