from __future__ import annotations

import shutil
from pathlib import Path

from db import insert_observations
from kismet import parse_kismet_db
from localize import recompute_networks
from paths import user_incoming
from wigle import parse_wigle_csv


def detect_format(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".kismet") or name.endswith(".kismet.db"):
        return "kismet"
    if name.endswith(".wiglecsv") or name.endswith(".csv"):
        # Peek header
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(512).lower()
            if "wigle" in head or "mac" in head and "ssid" in head:
                return "wigle"
        except OSError:
            pass
        if "wigle" in name:
            return "wigle"
    # sqlite magic
    try:
        with open(path, "rb") as f:
            magic = f.read(16)
        if magic.startswith(b"SQLite format 3"):
            return "kismet"
    except OSError:
        pass
    raise ValueError(f"Unrecognized file format: {path.name}")


def ingest_file_for_user(
    user_id: int,
    src: Path,
    *,
    mode: str = "2d",
    precision: str = "balanced",
    copy_to_incoming: bool = True,
) -> dict:
    dest = src
    if copy_to_incoming:
        incoming = user_incoming(user_id)
        dest = incoming / src.name
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)

    fmt = detect_format(dest)
    if fmt == "kismet":
        rows = parse_kismet_db(dest)
    else:
        rows = parse_wigle_csv(dest)

    n = insert_observations(rows, user_id=user_id)
    network_ids = list({r[1] for r in rows})
    # Positions first (map / turn-by-turn). Addresses fill in via low-prio job.
    updated = recompute_networks(
        network_ids,
        mode=mode,
        user_id=user_id,
        precision=precision,
        geocode=False,
    )
    geocode_job_id = None
    try:
        from jobs import enqueue_job

        job = enqueue_job(
            user_id,
            "geocode",
            {"network_ids": network_ids, "only_missing": False, "priority": 50},
        )
        geocode_job_id = job.get("id")
    except Exception:
        pass
    return {
        "file": dest.name,
        "format": fmt,
        "samples_submitted": n,
        "networks_updated": updated,
        "geocode_job_id": geocode_job_id,
        "path": str(dest),
    }
