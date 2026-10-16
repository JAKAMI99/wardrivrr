#!/usr/bin/env python3
"""
Backfill encryption on signal_samples / networks from Kismet device JSON.

Root cause: older imports never read kismet.device.base.crypt.
Re-run after fixing backend/kismet.py, or anytime Enc looks empty.

Usage (repo root):
  python scripts/backfill_kismet_encryption.py
  python scripts/backfill_kismet_encryption.py --path data/incoming
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
        "--path",
        default=str(ROOT / "data"),
        help="Directory to scan for *.kismet files",
    )
    args = parser.parse_args()

    from db import connect
    from kismet import _load_device_index, is_kismet_db
    from wigle import normalize_encryption
    import sqlite3

    root = Path(args.path)
    files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and (
            p.suffix.lower() == ".kismet"
            or p.name.lower().endswith(".kismet.db")
        )
    )
    print(f"[enc-backfill] found {len(files)} candidate files under {root}", flush=True)

    # MAC -> best encryption label
    mac_enc: dict[str, str] = {}
    for path in files:
        if not is_kismet_db(path):
            continue
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            print(f"[enc-backfill] skip {path.name}: {exc}", flush=True)
            continue
        try:
            index = _load_device_index(conn)
        except sqlite3.DatabaseError as exc:
            print(f"[enc-backfill] skip {path.name}: {exc}", flush=True)
            conn.close()
            continue
        finally:
            try:
                conn.close()
            except Exception:
                pass
        for mac, meta in index.items():
            raw = meta.get("encryption")
            if not raw:
                continue
            label = normalize_encryption(raw)
            if label in {"None", "Unknown"}:
                # Still record Open as None — only overwrite if we have stronger later
                mac_enc.setdefault(mac, label)
            else:
                mac_enc[mac] = label
        print(f"[enc-backfill] {path.name}: {len(index)} devices", flush=True)

    useful = {m: e for m, e in mac_enc.items() if e not in {"None", "Unknown"}}
    print(f"[enc-backfill] MACs with real crypt: {len(useful)}", flush=True)
    if not useful:
        print("[enc-backfill] nothing to apply", flush=True)
        return 0

    # Sorted for stable lock order; commit in chunks to avoid long deadlocks
    items = sorted(useful.items(), key=lambda x: x[0])
    pg = connect()
    updated_samples = 0
    updated_networks = 0
    chunk = 200
    try:
        with pg.cursor() as cur:
            cur.execute("SET lock_timeout = '5s'")
            for i in range(0, len(items), chunk):
                batch = items[i : i + chunk]
                for attempt in range(3):
                    try:
                        for mac, enc in batch:
                            cur.execute(
                                """
                                UPDATE signal_samples
                                SET encryption = %s
                                WHERE network_id = %s
                                  AND (encryption IS NULL OR encryption IN ('None', 'Unknown', ''))
                                """,
                                (enc, mac),
                            )
                            updated_samples += cur.rowcount
                            cur.execute(
                                """
                                UPDATE networks
                                SET encryption = %s
                                WHERE network_id = %s
                                  AND (encryption IS NULL OR encryption IN ('None', 'Unknown', ''))
                                """,
                                (enc, mac),
                            )
                            updated_networks += cur.rowcount
                        pg.commit()
                        break
                    except Exception as exc:
                        pg.rollback()
                        if attempt == 2:
                            print(f"[enc-backfill] chunk {i} failed: {exc}", flush=True)
                        else:
                            import time

                            time.sleep(0.5 * (attempt + 1))
                if (i // chunk) % 10 == 0:
                    print(
                        f"[enc-backfill] progress {min(i + chunk, len(items))}/{len(items)}",
                        flush=True,
                    )
    finally:
        pg.close()

    print(
        f"[enc-backfill] updated samples≈{updated_samples}, networks≈{updated_networks}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
