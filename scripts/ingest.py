#!/usr/bin/env python3
"""Load Kismet DB and/or WiGLE CSV into PostGIS, then recompute 2D network locations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.db import connect, insert_observations  # noqa: E402
from backend.localize import recompute_2d, recompute_3d  # noqa: E402
from backend.wigle import load_path  # noqa: E402

SUFFIXES = {".csv", ".txt", ".wiglecsv", ".db", ".sqlite", ".sqlite3", ".kismet", ".kis_db"}


def iter_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.suffix.lower() in SUFFIXES))
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest Kismet (.kismet/.kis_db) and/or WiGLE CSV into signal_samples."
    )
    parser.add_argument("paths", nargs="*", type=Path, help="Files or directories to import")
    parser.add_argument("--truncate", action="store_true", help="Wipe samples + networks before import")
    parser.add_argument(
        "--recompute-3d",
        action="store_true",
        help="After import (or alone), recompute all networks with the opt-in 3D formula",
    )
    parser.add_argument(
        "--recompute-only",
        action="store_true",
        help="Skip file import; only run localization (2d unless --recompute-3d)",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=1,
        help="Owner user_id for samples/networks (default: 1 / bootstrap admin)",
    )
    parser.add_argument(
        "--precision",
        choices=("fast", "balanced", "precise"),
        default="balanced",
        help="Localization sample-cap preset",
    )
    args = parser.parse_args()

    if not args.recompute_only and not args.paths:
        parser.error("provide paths to import, or use --recompute-only")

    user_id = args.user_id
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        print("[+] PostGIS connection ok")

        if args.truncate:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM signal_samples WHERE user_id = %s", (user_id,))
                cur.execute("DELETE FROM networks WHERE user_id = %s", (user_id,))
            conn.commit()
            print(f"[*] Cleared samples/networks for user_id={user_id}")

        touched: set[str] = set()
        total = 0

        if not args.recompute_only:
            files = iter_files(args.paths)
            if not files:
                print("No supported files found.")
                return 1

            for file_path in files:
                print(f"[*] Parsing {file_path}")
                try:
                    rows = load_path(file_path)
                except Exception as exc:
                    print(f"    ERROR: {exc}")
                    continue
                print(f"    {len(rows)} usable samples")
                for row in rows:
                    touched.add(row[1])
                inserted = insert_observations(rows, conn=conn, user_id=user_id)
                total += inserted
                print(f"    submitted {inserted} (duplicates ignored)")

            if touched:
                n = recompute_2d(
                    sorted(touched), conn=conn, user_id=user_id, precision=args.precision
                )
                print(f"[+] 2D recompute updated {n} networks")

        if args.recompute_3d:
            n = recompute_3d(None, conn=conn, user_id=user_id, precision=args.precision)
            print(f"[+] 3D recompute updated {n} networks (opt-in)")
        elif args.recompute_only:
            n = recompute_2d(None, conn=conn, user_id=user_id, precision=args.precision)
            print(f"[+] 2D recompute updated {n} networks")

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM signal_samples WHERE user_id = %s", (user_id,)
            )
            samples = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM networks WHERE user_id = %s", (user_id,))
            networks = cur.fetchone()[0]
        print(
            f"[+] Done. user_id={user_id} signal_samples={samples} networks={networks} submitted_this_run={total}"
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
