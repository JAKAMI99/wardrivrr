from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("DATA_ROOT") or ROOT / "data").expanduser().resolve()
USERS = DATA / "users"
LEVELS_SHARED = DATA / "levels"


def user_dir(user_id: int) -> Path:
    path = USERS / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_incoming(user_id: int) -> Path:
    path = user_dir(user_id) / "incoming"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_exports(user_id: int) -> Path:
    path = user_dir(user_id) / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def level_dir(user_id: int, level_id: int) -> Path:
    path = user_dir(user_id) / "levels" / str(level_id)
    path.mkdir(parents=True, exist_ok=True)
    return path
