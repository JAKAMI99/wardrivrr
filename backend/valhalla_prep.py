"""
Prepare Valhalla input under data/valhalla/active.osm.pbf.

Regional Geofabrik packs live in data/pbf/{extract}.osm.pbf (e.g. Arnsberg…).
Valhalla only sees data/valhalla/ (compose bind mount). We either:
  - seed active.osm.pbf from a regional pack (first download → full tile build), or
  - clip the pack to the level bbox (faster, Navigate prepare).
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
from cpu_workers import valhalla_server_threads
from levels import get_level
from paths import DATA, ROOT

PBF_DIR = DATA / "pbf"
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


def _write_meta(
    *,
    source: str,
    level: dict | None = None,
    bbox: list[float] | None = None,
    mode: str = "seed",
) -> None:
    payload: dict[str, Any] = {
        "mode": mode,
        "source_pbf": source,
        "updated_at": time.time(),
    }
    if level:
        payload["level_id"] = level["id"]
        payload["name"] = level.get("name")
        payload["geofabrik_id"] = level.get("geofabrik_id")
    if bbox is not None:
        payload["bbox"] = [round(x, 6) for x in bbox]
    ACTIVE_META.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def list_regional_pbfs() -> list[Path]:
    """Regional packs in data/pbf (any *.osm.pbf / *.pbf), largest first."""
    if not PBF_DIR.is_dir():
        return []
    found: list[Path] = []
    for path in PBF_DIR.iterdir():
        if not path.is_file():
            continue
        name = path.name.lower()
        if name.endswith(".osm.pbf") or name.endswith(".pbf"):
            if path.stat().st_size >= 1000:
                found.append(path)
    found.sort(key=lambda p: p.stat().st_size, reverse=True)
    return found


def pick_regional_pbf(preferred: Path | None = None) -> Path | None:
    if preferred is not None and preferred.is_file() and preferred.stat().st_size >= 1000:
        return preferred
    packs = list_regional_pbfs()
    return packs[0] if packs else None


def active_pbf_ready() -> bool:
    try:
        return ACTIVE_PBF.is_file() and ACTIVE_PBF.stat().st_size >= 1000
    except OSError:
        return False


def _link_or_copy(src: Path, dest: Path) -> str:
    """Prefer hardlink (same FS), else copy. Returns method used."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.osm.pbf")
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    try:
        os.link(src, tmp)
        method = "hardlink"
    except OSError:
        shutil.copy2(src, tmp)
        method = "copy"
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    tmp.replace(dest)
    return method


def wipe_valhalla_tiles() -> None:
    tiles = VALHALLA_DIR / "valhalla_tiles"
    if tiles.exists():
        shutil.rmtree(tiles, ignore_errors=True)
    subprocess.run(
        ["docker", "volume", "rm", "-f", "wardrivrr_valhalla_data"],
        capture_output=True,
        text=True,
        timeout=60,
    )


def seed_active_from_regional(
    src: Path | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """
    Ensure data/valhalla/active.osm.pbf exists by linking/copying a regional pack
    from data/pbf (e.g. Arnsberg….osm.pbf). Does not start Valhalla.
    """
    src = pick_regional_pbf(src)
    if src is None:
        raise ValhallaPrepError(
            "No regional map pack in data/pbf/*.osm.pbf — download a Geofabrik extract first"
        )

    VALHALLA_DIR.mkdir(parents=True, exist_ok=True)
    if ACTIVE_PBF.is_dir():
        shutil.rmtree(ACTIVE_PBF, ignore_errors=True)

    already = (
        not force
        and active_pbf_ready()
        and ACTIVE_PBF.stat().st_size == src.stat().st_size
    )
    if already and ACTIVE_META.exists():
        try:
            meta = json.loads(ACTIVE_META.read_text(encoding="utf-8"))
            if meta.get("source_pbf") == str(src) and meta.get("mode") in (
                "seed",
                "clip",
            ):
                return {
                    "ok": True,
                    "seeded": False,
                    "already_current": True,
                    "source_pbf": str(src),
                    "active_pbf": str(ACTIVE_PBF),
                    "active_bytes": ACTIVE_PBF.stat().st_size,
                }
        except (OSError, json.JSONDecodeError):
            pass

    # If a level clip already matches a different size, only overwrite when forced
    # or when active is missing. First-PBF path uses force=False but active missing.
    if active_pbf_ready() and not force:
        if ACTIVE_META.exists():
            try:
                meta = json.loads(ACTIVE_META.read_text(encoding="utf-8"))
                if meta.get("mode") == "clip":
                    return {
                        "ok": True,
                        "seeded": False,
                        "already_current": True,
                        "detail": "Level clip already active — skip regional seed",
                        "source_pbf": str(src),
                        "active_pbf": str(ACTIVE_PBF),
                        "active_bytes": ACTIVE_PBF.stat().st_size,
                    }
            except (OSError, json.JSONDecodeError):
                pass

    method = _link_or_copy(src, ACTIVE_PBF)
    _write_meta(source=str(src), mode="seed")
    return {
        "ok": True,
        "seeded": True,
        "already_current": False,
        "method": method,
        "source_pbf": str(src),
        "active_pbf": str(ACTIVE_PBF),
        "active_bytes": ACTIVE_PBF.stat().st_size,
    }


def _compose_root() -> Path:
    """Host checkout with docker-compose.yml (API may use a bind-mounted path)."""
    env = (os.getenv("WARDRIVRR_COMPOSE_ROOT") or "").strip()
    if env:
        return Path(env)
    return ROOT


def _host_data_root() -> Path:
    """Host path for ./data — required when docker run mounts from inside the API container."""
    env = (os.getenv("HOST_DATA_ROOT") or "").strip()
    if env:
        return Path(env)
    return DATA


def _compose_cmd() -> list[str]:
    root = _compose_root()
    compose = ["docker", "compose", "-f", str(root / "docker-compose.yml")]
    car = root / "deploy" / "compose.car.yml"
    if car.is_file():
        compose.extend(["-f", str(car)])
    env_file = root / ".env"
    if env_file.is_file():
        compose.extend(["--env-file", str(env_file)])
    return compose


def _compose_env() -> dict[str, str]:
    """Shell env for compose — scales Valhalla threads to accessible cores."""
    env = {k: str(v) for k, v in os.environ.items() if v is not None}
    threads = str(valhalla_server_threads())
    env["VALHALLA_SERVER_THREADS"] = threads
    return env


def _restart_valhalla(*, wipe: bool | None = None) -> dict[str, Any]:
    """Recreate Valhalla so it rebuilds tiles from data/valhalla/active.osm.pbf."""
    if not active_pbf_ready():
        raise ValhallaPrepError("active.osm.pbf missing — seed or clip first")

    compose = _compose_cmd()
    root = _compose_root()
    if not (root / "docker-compose.yml").is_file():
        raise ValhallaPrepError(
            f"docker-compose.yml not found at {root} — set WARDRIVRR_COMPOSE_ROOT"
        )

    cenv = _compose_env()
    threads = cenv["VALHALLA_SERVER_THREADS"]
    steps: list[dict[str, Any]] = []
    for args in (
        ["stop", "valhalla"],
        ["rm", "-f", "valhalla"],
    ):
        proc = subprocess.run(
            [*compose, *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
            env=cenv,
        )
        steps.append({"cmd": args, "code": proc.returncode})

    do_wipe = os.getenv("VALHALLA_WIPE_ON_LEVEL", "1") != "0" if wipe is None else wipe
    if do_wipe:
        wipe_valhalla_tiles()
        steps.append({"cmd": ["wipe_tiles"], "code": 0})

    proc = subprocess.run(
        [*compose, "up", "valhalla", "-d"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=120,
        env=cenv,
    )
    steps.append(
        {
            "cmd": ["up", "-d"],
            "code": proc.returncode,
            "err": (proc.stderr or "")[-400:],
            "server_threads": threads,
        }
    )
    if proc.returncode != 0:
        raise ValhallaPrepError(f"Could not start Valhalla: {proc.stderr or proc.stdout}")
    return {
        "restarted": True,
        "wiped_tiles": do_wipe,
        "server_threads": int(threads),
        "steps": steps,
    }


def ensure_valhalla_after_regional_pbf(
    src: Path | None = None,
    *,
    force_seed: bool = False,
    restart: bool = True,
) -> dict[str, Any]:
    """
    After the first (or any) regional pack lands in data/pbf: seed active.osm.pbf
    and recreate Valhalla for a full tile rebuild.
    """
    seed = seed_active_from_regional(src, force=force_seed)
    out: dict[str, Any] = {"ok": True, "seed": seed}
    if not restart:
        return out
    if seed.get("seeded") or force_seed or not seed.get("already_current"):
        try:
            out["valhalla"] = _restart_valhalla(wipe=True)
        except ValhallaPrepError as exc:
            out["valhalla"] = {
                "restarted": False,
                "detail": str(exc),
                "hint": "Run ./run.sh on the host to start Valhalla",
            }
    else:
        out["valhalla"] = {
            "restarted": False,
            "detail": "Active PBF already seeded from this pack",
        }
    return out


def _clip_with_osmium_docker(src: Path, dest: Path, bbox: list[float]) -> None:
    """osmium extract via Docker (reliable on Windows hosts)."""
    west, south, east, north = bbox
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.osm.pbf")
    if tmp.exists():
        tmp.unlink()

    # Mount host data dir so the Docker daemon (often on the host) sees real paths
    data_root = _host_data_root().resolve()
    try:
        rel_src = src.resolve().relative_to(DATA.resolve()).as_posix()
        rel_tmp = tmp.resolve().relative_to(DATA.resolve()).as_posix()
    except ValueError as exc:
        raise ValhallaPrepError(f"PBF paths must live under data/: {exc}") from exc

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
        # Fall back to any regional pack (renamed / short id)
        alt = pick_regional_pbf()
        if alt is None:
            raise ValhallaPrepError(f"Map pack PBF missing for {gid}: {src}")
        src = alt

    VALHALLA_DIR.mkdir(parents=True, exist_ok=True)
    if ACTIVE_PBF.is_dir():
        shutil.rmtree(ACTIVE_PBF, ignore_errors=True)

    clipped = False
    if force or not _meta_matches(level_id, padded):
        _clip_with_osmium_docker(src, ACTIVE_PBF, padded)
        _write_meta(source=str(src), level=level, bbox=padded, mode="clip")
        clipped = True

    out: dict[str, Any] = {
        "ok": True,
        "level_id": level_id,
        "name": level.get("name"),
        "bbox": padded,
        "active_pbf": str(ACTIVE_PBF),
        "active_bytes": ACTIVE_PBF.stat().st_size if ACTIVE_PBF.exists() else 0,
        "source_bytes": src.stat().st_size,
        "source_pbf": str(src),
        "clipped": clipped,
        "already_current": not clipped,
    }

    if restart and (clipped or force):
        out["valhalla"] = _restart_valhalla(wipe=True)
    elif restart and not clipped:
        out["valhalla"] = {
            "restarted": False,
            "detail": "Active clip already matches this level — no rebuild",
        }
    return out
