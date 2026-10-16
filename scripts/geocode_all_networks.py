#!/usr/bin/env python3
"""
Fill addresses for triangulated networks using all logical CPU threads.

Positions must already exist (localize first). This only reverse-geocodes.

Usage (repo root):
  python scripts/geocode_all_networks.py
  python scripts/geocode_all_networks.py --only-missing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Skip networks that already have an address",
    )
    parser.add_argument("--user-id", type=int, default=None)
    args = parser.parse_args()

    from cities_db import ensure_cities_db
    from geocode_worker import geocode_networks, logical_thread_count
    from local_geocode import ensure_postal_db

    print("[geocode-all] ensuring offline DBs…")
    ensure_cities_db()
    ensure_postal_db()
    print(f"[geocode-all] logical threads={logical_thread_count()}")

    def progress(frac, done, total):
        print(f"[geocode-all] {done}/{total} ({frac * 100:.1f}%)", flush=True)

    result = geocode_networks(
        user_id=args.user_id,
        only_missing=args.only_missing,
        progress_cb=progress,
    )
    print(f"[geocode-all] done: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
