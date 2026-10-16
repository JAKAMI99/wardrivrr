#!/usr/bin/env python3
"""
Build (or rebuild) the offline OSM address pack for an existing level.

Does not re-download roads — only scans the regional PBF for addr:* inside
the level bbox/boundary.

Usage (repo root):
  python scripts/build_level_addresses.py --user-id 1 --level-id 8
  python scripts/build_level_addresses.py --user-id 1 --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _levels(user_id: int | None, level_id: int | None, all_levels: bool):
    from db import connect

    conn = connect()
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT id, user_id, name, geofabrik_id, status,
                       CASE WHEN bbox IS NOT NULL THEN
                         ARRAY[ST_XMin(bbox), ST_YMin(bbox), ST_XMax(bbox), ST_YMax(bbox)]
                       END AS bbox_arr,
                       CASE WHEN bbox IS NOT NULL THEN
                         ST_AsGeoJSON(bbox)::json
                       END AS boundary
                FROM levels
                WHERE status = 'ready'
            """
            params: list = []
            if user_id is not None:
                sql += " AND user_id = %s"
                params.append(user_id)
            if level_id is not None and not all_levels:
                sql += " AND id = %s"
                params.append(level_id)
            sql += " ORDER BY id"
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument("--level-id", type=int, default=None)
    parser.add_argument("--all", action="store_true", help="All ready levels")
    args = parser.parse_args()
    if args.level_id is None and not args.all:
        parser.error("pass --level-id or --all")

    from address_index import build_level_address_pack
    from admin_areas import pbf_path_for_extract
    from paths import level_dir

    rows = _levels(args.user_id, args.level_id, args.all)
    if not rows:
        print("[addresses] no matching ready levels", flush=True)
        return 1

    for level in rows:
        uid, lid = int(level["user_id"]), int(level["id"])
        gid = level.get("geofabrik_id") or ""
        pbf = pbf_path_for_extract(gid)
        if not pbf.exists():
            local = level_dir(uid, lid) / "extract.osm.pbf"
            pbf = local if local.exists() else pbf
        if not pbf.exists():
            print(f"[addresses] level {lid}: missing PBF for {gid}", flush=True)
            continue
        bbox = level.get("bbox_arr")
        if bbox and hasattr(bbox, "tolist"):
            bbox = list(bbox)
        boundary = level.get("boundary")
        if isinstance(boundary, str):
            try:
                boundary = json.loads(boundary)
            except Exception:
                boundary = None
        print(f"[addresses] level {lid} ({level.get('name')}) ← {pbf.name}", flush=True)

        def progress(msg: str, _lid=lid):
            print(f"[addresses] {_lid}: {msg}", flush=True)

        info = build_level_address_pack(
            uid,
            lid,
            pbf,
            bbox=bbox,
            boundary=boundary if isinstance(boundary, dict) else None,
            progress=progress,
        )
        print(f"[addresses] level {lid}: {info['count']:,} addresses → {info['path']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
