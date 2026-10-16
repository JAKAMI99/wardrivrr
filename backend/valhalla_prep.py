"""
Clip the regional Geofabrik PBF to the active level bbox for Valhalla.

Full Regierungsbezirk extracts are huge; a city-sized clip builds in minutes
instead of much longer and keeps routing inside the loaded level.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from admin_areas import pbf_path_for_extract
from levels import get_level
from paths import DATA, ROOT

VALHALLA_DIR = DATA / "valhalla"
ACTIVE_PBF = VALHALLA_DIR / "active.osm.pbf"
ACTIVE_META = VALHALLA_DIR / "active.json"
# Soft pad so routes can briefly leave the admin edge (metres → degrees ~ at mid-lat)
BBOX_PAD_DEG = 0.02  # ~1.5–2 km


class ValhallaPrepError(RuntimeError):
    pass


def _pad_bbox(bbox: list[float], pad: float = BBOX_PAD_DEG) -> list[float]:
    west, south, east, north = (float(x) for x in bbox)
    return [
        max(-180.0, west - pad),
        max(-90.0, south - pad),
        min(180.0, east + pad),
        min(90.0, north + pad),
    ]


def _meta_matches(level_id: int, bbox: list[float]) -> bool:
    if not ACTIVE_PBF.exists() or ACTIVE_PBF.stat().st_size < 1000:
        return False
    if not ACTIVE_META.exists():
        return False
    try:
        meta = json.loads(ACTIVE_META.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        int(meta.get("level_id") or -1) == int(level_id)
        and meta.get("bbox") == [round(x, 6) for x in bbox]
    )


def _write_meta(level: dict, bbox: list[float], source: str) -> None:
    ACTIVE_META.write_text(
        json.dumps(
            {
                "level_id": level["id"],
                "name": level.get("name"),
                "geofabrik_id": level.get("geofabrik_id"),
                "bbox": [round(x, 6) for x in bbox],
                "source_pbf": source,
                "updated_at": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _clip_with_osmium_docker(src: Path, dest: Path, bbox: list[float]) -> None:
    """osmium extract via Docker (reliable on Windows hosts)."""
    west, south, east, north = bbox
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.osm.pbf")
    if tmp.exists():
        tmp.unlink()

    # Mount parent dirs so paths stay simple inside the container
    data_root = str(DATA.resolve())
    rel_src = src.resolve().relative_to(DATA.resolve()).as_posix()
    rel_tmp = tmp.resolve().relative_to(DATA.resolve()).as_posix()

    # iboates/osmium image ENTRYPOINT is already `osmium`
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{data_root}:/data",
        "iboates/osmium:latest",
        "extract",
        "--strategy=complete_ways",
        f"--bbox={west},{south},{east},{north}",
        "-o",
        f"/data/{rel_tmp}",
        f"/data/{rel_src}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1000:
        err = (proc.stderr or proc.stdout or "").strip()[-800:]
        raise ValhallaPrepError(f"osmium extract failed: {err or 'no output'}")
    tmp.replace(dest)


def _restart_valhalla() -> dict[str, Any]:
    """Recreate Valhalla so it rebuilds tiles from data/valhalla/active.osm.pbf."""
    car = ROOT / "deploy" / "compose.car.yml"
    compose = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
    if car.is_file():
        compose.extend(["-f", str(car)])
    if (ROOT / ".env").is_file():
        compose.extend(["--env-file", str(ROOT / ".env")])
    steps = []
    for args in (
        ["stop", "valhalla"],
        ["rm", "-f", "valhalla"],
    ):
        proc = subprocess.run(
            [*compose, *args], cwd=str(ROOT), capture_output=True, text=True, timeout=120
        )
        steps.append({"cmd": args, "code": proc.returncode})

    # Drop built tiles under the bind mount (named volume no longer used)
    wipe = os.getenv("VALHALLA_WIPE_ON_LEVEL", "1") != "0"
    if wipe:
        tiles = VALHALLA_DIR / "valhalla_tiles"
        if tiles.exists():
            shutil.rmtree(tiles, ignore_errors=True)
        steps.append({"cmd": ["rmtree", str(tiles)], "code": 0})
        # Legacy named volume from older compose
        subprocess.run(
            ["docker", "volume", "rm", "-f", "wardrivrr_valhalla_data"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    proc = subprocess.run(
        [*compose, "up", "valhalla", "-d"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    steps.append({"cmd": ["up", "-d"], "code": proc.returncode, "err": (proc.stderr or "")[-400:]})
    if proc.returncode != 0:
        raise ValhallaPrepError(f"Could not start Valhalla: {proc.stderr or proc.stdout}")
    return {"restarted": True, "wiped_tiles": wipe, "steps": steps}


def prepare_valhalla_for_level(
    user_id: int,
    level_id: int,
    *,
    restart: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """
    Ensure data/valhalla/active.osm.pbf is a bbox clip of the level's map pack.
    Optionally recreate the Valhalla container to rebuild tiles from that clip.
    """
    level = get_level(user_id, level_id)
    if not level:
        raise ValhallaPrepError("Level not found")
    if level.get("status") != "ready":
        raise ValhallaPrepError("Level is not ready")

    bbox = level.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValhallaPrepError("Level has no bbox — rebuild the level")
    bbox = [float(x) for x in bbox]
    padded = _pad_bbox(bbox)

    gid = level.get("geofabrik_id") or ""
    src = pbf_path_for_extract(gid)
    if not src.exists() or src.stat().st_size < 1000:
        raise ValhallaPrepError(f"Map pack PBF missing for {gid}: {src}")

    VALHALLA_DIR.mkdir(parents=True, exist_ok=True)
    clipped = False
    if force or not _meta_matches(level_id, padded):
        _clip_with_osmium_docker(src, ACTIVE_PBF, padded)
        _write_meta(level, padded, str(src))
        clipped = True

    out: dict[str, Any] = {
        "ok": True,
        "level_id": level_id,
        "name": level.get("name"),
        "bbox": padded,
        "active_pbf": str(ACTIVE_PBF),
        "active_bytes": ACTIVE_PBF.stat().st_size if ACTIVE_PBF.exists() else 0,
        "source_bytes": src.stat().st_size,
        "clipped": clipped,
        "already_current": not clipped,
    }

    if restart and (clipped or force):
        out["valhalla"] = _restart_valhalla()
    elif restart and not clipped:
        out["valhalla"] = {
            "restarted": False,
            "detail": "Active clip already matches this level — no rebuild",
        }
    return out
