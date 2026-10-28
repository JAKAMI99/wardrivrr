"""
Achievement catalog + progress.
"""

from __future__ import annotations

import math
import os
import threading
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from db import connect, connect_dict

ACHIEVEMENTS_TZ = os.getenv("ACHIEVEMENTS_TZ") or os.getenv("STATS_TZ") or "Europe/Berlin"

# Max metres credited between two fixes (anti-teleport)
_MAX_STEP_M = 250.0
# Ignore gaps longer than this between fixes
_MAX_GAP_S = 120.0
# Distance is credited from an anchor once the car has moved this far, so
# parked GPS jitter (a few metres per fix at 5 Hz) never adds up to km.
_MIN_STEP_M = 10.0
# Reported speed below this means parked / walking in place.
_MIN_SPEED_MPS = 0.8
_km_anchor: dict[int, tuple[float, float, float]] = {}
_km_anchor_lock = threading.Lock()

_schema_ready = False
_schema_lock = threading.Lock()

_last_eval_at: dict[int, float] = {}
_eval_lock = threading.Lock()
ACH_EVAL_MIN_INTERVAL_S = float(os.getenv("ACH_EVAL_MIN_INTERVAL_S", "15"))

# Activity XP (on top of achievement unlock XP) - networks + fog tiles.
# Radio finds stay low so fog tiles stay the main progression driver.
XP_PER_WIFI_NET = 1
XP_PER_BT_NET = 1
XP_PER_BLE_NET = 1
# First unlock of a fog tile (segment)
XP_PER_TILE = 2
# Re-driving an already unlocked tile (smaller credit)
XP_PER_OLD_TILE = 1

def _fmt_threshold(n: float | int) -> str:
    """Human-readable threshold for goal copy (e.g. 1,000,000 or 133.7)."""
    f = float(n)
    if abs(f - round(f)) < 1e-9:
        return f"{int(round(f)):,}"
    return f"{f:g}"


def _unit_label(unit: str) -> str:
    if unit.startswith("km"):
        return "km"
    if unit == "networks_total":
        return "networks"
    if unit in ("samples_below_sea", "samples_mountain"):
        return "samples"
    if unit == "starlink_networks":
        return "Starlink hotspots"
    if unit == "flipper_networks":
        return "Flipper Zeros"
    if unit == "segments_explored":
        return "tiles"
    return ""


def _how_for_tier(unit: str, threshold: float | int, override: str | None = None) -> str:
    if override:
        return override
    t = _fmt_threshold(threshold)
    if unit == "km_night_total":
        return f"Drive {t} km between 00:00-06:00"
    if unit == "km_day_best":
        return f"Drive {t} km in one calendar day"
    if unit == "networks_total":
        return f"Collect {t} triangulated networks"
    if unit == "samples_below_sea":
        return f"Collect {t} observation points below 0 m altitude"
    if unit == "samples_mountain":
        return f"Collect {t} observation points above 700 m altitude"
    if unit == "starlink_networks":
        return f"Detect {t} distinct Starlink hotspots"
    if unit == "flipper_networks":
        return f"Spot {t} distinct Flipper Zero{'s' if float(threshold) != 1 else ''}"
    if unit == "segments_explored":
        return f"Unlock {t} road tiles across your levels"
    return f"Reach {t}"


def _tier(
    n: int,
    threshold: float | int,
    unit: str,
    title: str,
    xp: int,
    *,
    master: bool = False,
) -> dict[str, Any]:
    return {
        "tier": n,
        "threshold": threshold,
        "unit": unit,
        "title": title,
        "xp": xp,
        "master": master,
    }


CATALOG: list[dict[str, Any]] = [
    {
        "id": "night_owl",
        "title": "Night owl",
        "description": "Drive between 00:00 and 06:00 local time.",
        "flavour": "The APs never sleep. Neither do you.",
        "tiers": [
            _tier(1, 50.0, "km_night_total", "Night owl", 400),
            _tier(2, 200.0, "km_night_total", "Night owl II", 1200),
            _tier(3, 500.0, "km_night_total", "Night owl III", 3000),
            _tier(4, 1500.0, "km_night_total", "Night owl IV", 7000),
            _tier(5, 5000.0, "km_night_total", "Night owl Mastered", 15000, master=True),
        ],
    },
    {
        "id": "memelord",
        "title": "Memelord",
        "description": "Drive a meme distance in a single calendar day.",
        "flavour": "42 -> 67 -> 133.7. Respect the lore.",
        "tiers": [
            _tier(1, 42.0, "km_day_best", "Memelord", 500),
            _tier(2, 67.0, "km_day_best", "Memelord II", 1500),
            _tier(3, 133.7, "km_day_best", "Memelord III", 4000),
            _tier(4, 420.0, "km_day_best", "Memelord IV", 8000),
            _tier(5, 1337.0, "km_day_best", "Memelord Mastered", 16000, master=True),
        ],
    },
    {
        "id": "hack_all_the_things",
        "title": "Hack all the things",
        "description": "Collect triangulated networks in your local database.",
        "flavour": "More boxes. More packets. More everything.",
        "tiers": [
            _tier(1, 50_000, "networks_total", "Hack all the things", 1000),
            _tier(2, 150_000, "networks_total", "Hack all the things II", 3000),
            _tier(3, 300_000, "networks_total", "Hack all the things III", 6000),
            _tier(4, 500_000, "networks_total", "Hack all the things IV", 10000),
            _tier(5, 750_000, "networks_total", "Hack all the things Mastered", 18000, master=True),
        ],
    },
    {
        "id": "aden_pierce",
        "title": "Aden Pierce",
        "description": "Collect one million triangulated networks.",
        "flavour": "ctOS would be proud. Probably.",
        "tiers": [
            _tier(1, 1_000_000, "networks_total", "Aden Pierce", 20000, master=True),
        ],
    },
    {
        "id": "fog_eater",
        "title": "Fog eater",
        "description": "Unlock road tiles (chunks) across all your levels.",
        "flavour": "Eat the map. Leave no fog behind.",
        "tiers": [
            _tier(1, 1_000, "segments_explored", "Fog eater", 600),
            _tier(2, 5_000, "segments_explored", "Fog eater II", 2000),
            _tier(3, 20_000, "segments_explored", "Fog eater III", 5000),
            _tier(4, 50_000, "segments_explored", "Fog eater IV", 10000),
            _tier(5, 100_000, "segments_explored", "Fog eater Mastered", 22000, master=True),
        ],
    },
    {
        "id": "below_sea",
        "title": "Below sea",
        "description": "Collect observation points with GPS altitude below 0 m.",
        "flavour": "Dead reckoning in the bathyscape.",
        "tiers": [
            _tier(1, 500, "samples_below_sea", "Below sea", 800, master=True),
        ],
    },
    {
        "id": "mountainclimber",
        "title": "Mountainclimber",
        "description": "Collect observation points with GPS altitude above 700 m.",
        "flavour": "Thin air, thick RF.",
        "tiers": [
            _tier(1, 500, "samples_mountain", "Mountainclimber", 800, master=True),
        ],
    },
    {
        "id": "transmitting_to_space",
        "title": "Transmitting to space",
        "description": "Detect distinct Starlink user Wi-Fi hotspots (default STARLINK SSID).",
        "flavour": "Low Earth orbit, high RSSI envy.",
        "tiers": [
            _tier(1, 10, "starlink_networks", "Transmitting to space", 500),
            _tier(2, 50, "starlink_networks", "Transmitting to space II", 1500),
            _tier(3, 100, "starlink_networks", "Transmitting to space III", 4000),
            _tier(4, 250, "starlink_networks", "Transmitting to space IV", 8000),
            _tier(5, 500, "starlink_networks", "Transmitting to space Mastered", 15000, master=True),
        ],
    },
    {
        "id": "wall_of_flippers",
        "title": "Wall of Flippers",
        "description": "Spot distinct Flipper Zero devices (BLE MAC OUI or Flipper name).",
        "flavour": "80:E1:26 walking by. Don't pet the dolphin.",
        "tiers": [
            _tier(1, 1, "flipper_networks", "Wall of Flippers", 200),
            _tier(2, 3, "flipper_networks", "Wall of Flippers II", 500),
            _tier(3, 5, "flipper_networks", "Wall of Flippers III", 1000),
            _tier(4, 10, "flipper_networks", "Wall of Flippers IV", 2000),
            _tier(5, 20, "flipper_networks", "Wall of Flippers Mastered", 4000, master=True),
        ],
    },
]


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(ACHIEVEMENTS_TZ)
    except Exception:
        return ZoneInfo("UTC")


def ensure_achievements_schema() -> None:
    """Idempotent DDL; runs once per process (hot paths call this every tick)."""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        _create_achievements_schema()
        _schema_ready = True


def _create_achievements_schema() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS drive_day_km (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    day DATE NOT NULL,
                    km_total DOUBLE PRECISION NOT NULL DEFAULT 0,
                    km_night DOUBLE PRECISION NOT NULL DEFAULT 0,
                    km_explored DOUBLE PRECISION NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, day)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_achievements (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    achievement_id TEXT NOT NULL,
                    tier INTEGER NOT NULL DEFAULT 1,
                    unlocked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    meta JSONB NOT NULL DEFAULT '{}',
                    PRIMARY KEY (user_id, achievement_id, tier)
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS user_achievements_user_idx
                ON user_achievements(user_id)
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_activity_counters (
                    user_id INTEGER NOT NULL PRIMARY KEY
                      REFERENCES users(id) ON DELETE CASCADE,
                    tiles_revisited INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            # Existing unlocks count as already shown; new rows start NULL so
            # the Drive HUD can toast unlocks made by background collectors.
            cur.execute(
                """
                ALTER TABLE user_achievements
                ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ DEFAULT NOW()
                """
            )
            cur.execute(
                "ALTER TABLE user_achievements ALTER COLUMN notified_at DROP DEFAULT"
            )
        conn.commit()
    finally:
        conn.close()


def record_tile_revisits(user_id: int, count: int) -> int:
    """Credit re-drives of already unlocked fog tiles. Returns new total."""
    n = max(0, int(count or 0))
    if n <= 0:
        return 0
    ensure_achievements_schema()
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_activity_counters (user_id, tiles_revisited)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                  tiles_revisited = user_activity_counters.tiles_revisited
                    + EXCLUDED.tiles_revisited,
                  updated_at = NOW()
                RETURNING tiles_revisited
                """,
                (user_id, n),
            )
            row = cur.fetchone()
        conn.commit()
        return int(row[0] if row else 0)
    finally:
        conn.close()


def tiles_revisited_count(user_id: int) -> int:
    ensure_achievements_schema()
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tiles_revisited FROM user_activity_counters WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return int(row[0] if row else 0)
    finally:
        conn.close()


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _km_since_anchor(
    user_id: int,
    lat: float,
    lon: float,
    now_ts: float,
    speed_mps: float | None,
) -> float:
    """Distance moved since the last credited point; 0 while parked/jittering."""
    with _km_anchor_lock:
        anchor = _km_anchor.get(user_id)
        if (
            anchor is None
            or not (0 <= now_ts - anchor[2] <= _MAX_GAP_S)
            or (speed_mps is not None and speed_mps < _MIN_SPEED_MPS)
        ):
            _km_anchor[user_id] = (lat, lon, now_ts)
            return 0.0
        step_m = _haversine_m(anchor[0], anchor[1], lat, lon)
        if step_m < _MIN_STEP_M:
            return 0.0
        _km_anchor[user_id] = (lat, lon, now_ts)
        if step_m > _MAX_STEP_M:
            return 0.0
        return step_m / 1000.0


def record_drive_step(
    user_id: int,
    *,
    lat: float,
    lon: float,
    now_ts: float | None = None,
    explored_km_delta: float = 0.0,
    speed_mps: float | None = None,
) -> dict[str, Any]:
    """
    Credit distance moved (anchor-based, see _km_since_anchor) and fog km.
    Achievement evaluation is throttled; unlocks are toasted via pop_unnotified.
    """
    ensure_achievements_schema()
    tz = _tz()
    ts = float(now_ts) if now_ts is not None else time.time()
    now = datetime.fromtimestamp(ts, tz=tz)
    day = now.date()
    hour = now.hour
    is_night = 0 <= hour < 6

    added_km = _km_since_anchor(user_id, lat, lon, ts, speed_mps)
    explored_km = max(0.0, float(explored_km_delta or 0))
    if added_km <= 0 and explored_km <= 0:
        return {
            "added_km": 0.0,
            "day": day.isoformat(),
            "newly_unlocked": maybe_evaluate_achievements(user_id),
        }

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO drive_day_km (user_id, day, km_total, km_night, km_explored)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id, day) DO UPDATE SET
                  km_total = drive_day_km.km_total + EXCLUDED.km_total,
                  km_night = drive_day_km.km_night + EXCLUDED.km_night,
                  km_explored = drive_day_km.km_explored + EXCLUDED.km_explored,
                  updated_at = NOW()
                RETURNING km_total, km_night, km_explored
                """,
                (
                    user_id,
                    day,
                    added_km,
                    added_km if is_night else 0.0,
                    explored_km,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    newly = maybe_evaluate_achievements(user_id)
    return {
        "added_km": added_km,
        "day": day.isoformat(),
        "km_total": float(row[0] or 0) if row else 0.0,
        "km_night": float(row[1] or 0) if row else 0.0,
        "km_explored": float(row[2] or 0) if row else 0.0,
        "newly_unlocked": newly,
    }


def _progress_snapshot(user_id: int) -> dict[str, Any]:
    tz = _tz()
    today = datetime.now(tz=tz).date()
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  COALESCE(SUM(km_night), 0)::float AS km_night_total,
                  COALESCE(MAX(km_total), 0)::float AS km_day_best
                FROM drive_day_km
                WHERE user_id = %s
                """,
                (user_id,),
            )
            agg = cur.fetchone() or {}
            cur.execute(
                """
                SELECT km_total, km_night, km_explored
                FROM drive_day_km WHERE user_id = %s AND day = %s
                """,
                (user_id, today),
            )
            today_row = cur.fetchone() or {}
            cur.execute(
                """
                SELECT
                  COUNT(*)::int AS n,
                  COUNT(*) FILTER (
                    WHERE upper(coalesce(network_type, '')) IN (
                      'WIFI', 'W', 'WLAN', '802.11', 'IEEE802.11', 'WI-FI'
                    )
                    OR upper(coalesce(network_type, '')) LIKE '%%WIFI%%'
                    OR upper(coalesce(network_type, '')) LIKE '%%802.11%%'
                  )::int AS wifi,
                  COUNT(*) FILTER (
                    WHERE upper(coalesce(network_type, '')) IN (
                      'BT', 'BLUETOOTH', 'BR/EDR'
                    )
                    OR (
                      upper(coalesce(network_type, '')) LIKE '%%BT%%'
                      AND upper(coalesce(network_type, '')) NOT LIKE '%%BLE%%'
                      AND upper(coalesce(network_type, '')) NOT LIKE '%%BTLE%%'
                    )
                  )::int AS bt,
                  COUNT(*) FILTER (
                    WHERE upper(coalesce(network_type, '')) IN ('BLE', 'BTLE')
                    OR upper(coalesce(network_type, '')) LIKE '%%BLE%%'
                    OR upper(coalesce(network_type, '')) LIKE '%%BTLE%%'
                  )::int AS ble
                FROM networks WHERE user_id = %s
                """,
                (user_id,),
            )
            net_row = cur.fetchone() or {}
            networks_total = int(net_row.get("n") or 0)
            networks_wifi = int(net_row.get("wifi") or 0)
            networks_bt = int(net_row.get("bt") or 0)
            networks_ble = int(net_row.get("ble") or 0)
            # Mistyped / unknown radios still pay - treat leftovers as Wi-Fi
            typed = networks_wifi + networks_bt + networks_ble
            if networks_total > typed:
                networks_wifi += networks_total - typed
            cur.execute(
                """
                SELECT COALESCE(SUM(km_total), 0)::float AS km_driven_total,
                       COALESCE(SUM(km_explored), 0)::float AS km_explored_total
                FROM drive_day_km WHERE user_id = %s
                """,
                (user_id,),
            )
            km_row = cur.fetchone() or {}
            km_driven_total = float(km_row.get("km_driven_total") or 0)
            km_explored_total = float(km_row.get("km_explored_total") or 0)
            # Fog metres from the map itself (survives missed explored_km_delta credits)
            cur.execute(
                """
                SELECT COALESCE(SUM(rs.length_m), 0)::float AS m,
                       COUNT(*)::int AS n
                FROM road_segments rs
                JOIN levels l ON l.id = rs.level_id
                WHERE l.user_id = %s
                  AND rs.is_explored = TRUE
                """,
                (user_id,),
            )
            road_row = cur.fetchone() or {}
            road_explored_m = float(road_row.get("m") or 0.0)
            segments_explored = int(road_row.get("n") or 0)
            km_explored_total = max(
                km_explored_total, road_explored_m / 1000.0
            )
            cur.execute(
                """
                SELECT COUNT(*)::int AS n
                FROM signal_samples
                WHERE user_id = %s
                  AND altitude IS NOT NULL
                  AND altitude < 0
                """,
                (user_id,),
            )
            samples_below_sea = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute(
                """
                SELECT COUNT(*)::int AS n
                FROM signal_samples
                WHERE user_id = %s
                  AND altitude IS NOT NULL
                  AND altitude > 700
                """,
                (user_id,),
            )
            samples_mountain = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute(
                """
                SELECT achievement_id, tier, unlocked_at
                FROM user_achievements WHERE user_id = %s
                """,
                (user_id,),
            )
            unlocked_rows = cur.fetchall()
            cur.execute(
                """
                SELECT tiles_revisited FROM user_activity_counters WHERE user_id = %s
                """,
                (user_id,),
            )
            tiles_revisited = int((cur.fetchone() or {}).get("tiles_revisited") or 0)
    finally:
        conn.close()

    # Special-device progress only when anomaly alerts are enabled
    starlink_networks = 0
    flipper_networks = 0
    try:
        from anomalies import (
            anomaly_alerts_enabled,
            count_flipper_networks,
            count_starlink_networks,
        )

        if anomaly_alerts_enabled(user_id):
            starlink_networks = count_starlink_networks(user_id)
            flipper_networks = count_flipper_networks(user_id)
    except Exception:
        starlink_networks = 0
        flipper_networks = 0

    unlocked = {(r["achievement_id"], int(r["tier"])): r for r in unlocked_rows}
    return {
        "km_night_total": float(agg.get("km_night_total") or 0),
        "km_day_best": float(agg.get("km_day_best") or 0),
        "km_today": float(today_row.get("km_total") or 0),
        "km_night_today": float(today_row.get("km_night") or 0),
        "km_driven_total": km_driven_total,
        "km_explored_total": km_explored_total,
        "networks_total": networks_total,
        "networks_wifi": networks_wifi,
        "networks_bt": networks_bt,
        "networks_ble": networks_ble,
        "samples_below_sea": samples_below_sea,
        "samples_mountain": samples_mountain,
        "starlink_networks": starlink_networks,
        "flipper_networks": flipper_networks,
        "segments_explored": segments_explored,
        "tiles_revisited": tiles_revisited,
        "unlocked": unlocked,
        "today": today.isoformat(),
    }


def activity_xp_breakdown(
    snap: dict[str, Any],
    *,
    achievements_xp: int = 0,
) -> dict[str, Any]:
    """XP from networks, new/old fog tiles, and (optionally) achievements."""
    wifi = int(snap.get("networks_wifi") or 0)
    bt = int(snap.get("networks_bt") or 0)
    ble = int(snap.get("networks_ble") or 0)
    tiles_new = int(snap.get("segments_explored") or 0)
    tiles_old = int(snap.get("tiles_revisited") or 0)
    ach = max(0, int(achievements_xp or 0))
    from_wifi = wifi * XP_PER_WIFI_NET
    from_bt = bt * XP_PER_BT_NET
    from_ble = ble * XP_PER_BLE_NET
    from_tiles_new = tiles_new * XP_PER_TILE
    from_tiles_old = tiles_old * XP_PER_OLD_TILE
    activity_total = from_wifi + from_bt + from_ble + from_tiles_new + from_tiles_old
    breakdown = [
        {
            "id": "tiles_new",
            "label": "New tiles",
            "xp": from_tiles_new,
            "count": tiles_new,
            "rate": XP_PER_TILE,
        },
        {
            "id": "tiles_old",
            "label": "Old tiles",
            "xp": from_tiles_old,
            "count": tiles_old,
            "rate": XP_PER_OLD_TILE,
        },
        {
            "id": "wifi",
            "label": "Wi-Fi",
            "xp": from_wifi,
            "count": wifi,
            "rate": XP_PER_WIFI_NET,
        },
        {
            "id": "bt",
            "label": "Bluetooth",
            "xp": from_bt,
            "count": bt,
            "rate": XP_PER_BT_NET,
        },
        {
            "id": "ble",
            "label": "BLE",
            "xp": from_ble,
            "count": ble,
            "rate": XP_PER_BLE_NET,
        },
        {
            "id": "achievements",
            "label": "Achievements",
            "xp": ach,
            "count": None,
            "rate": None,
        },
    ]
    return {
        "wifi": from_wifi,
        "bt": from_bt,
        "ble": from_ble,
        "tiles": from_tiles_new,
        "tiles_new": from_tiles_new,
        "tiles_old": from_tiles_old,
        "achievements": ach,
        # Legacy keys
        "driven": 0,
        "new_road": from_tiles_new,
        "total": activity_total,
        "grand_total": activity_total + ach,
        "breakdown": breakdown,
        "counts": {
            "wifi": wifi,
            "bt": bt,
            "ble": ble,
            "tiles": tiles_new,
            "tiles_new": tiles_new,
            "tiles_old": tiles_old,
            "km": round(float(snap.get("km_driven_total") or 0), 3),
            "km_new": round(float(snap.get("km_explored_total") or 0), 3),
        },
        "rates": {
            "wifi": XP_PER_WIFI_NET,
            "bt": XP_PER_BT_NET,
            "ble": XP_PER_BLE_NET,
            "tiles": XP_PER_TILE,
            "tiles_new": XP_PER_TILE,
            "tiles_old": XP_PER_OLD_TILE,
        },
    }


def _achievement_xp_earned(snap: dict[str, Any]) -> int:
    total = 0
    unlocked = snap.get("unlocked") or {}
    for ach in CATALOG:
        for tier in ach["tiers"]:
            key = (ach["id"], int(tier["tier"]))
            if key in unlocked:
                total += int(tier.get("xp") or 0)
    return total


def _metric_value(snap: dict[str, Any], unit: str) -> float:
    if unit == "km_night_total":
        return float(snap["km_night_total"])
    if unit == "km_day_best":
        return float(snap["km_day_best"])
    if unit == "networks_total":
        return float(snap["networks_total"])
    if unit == "samples_below_sea":
        return float(snap["samples_below_sea"])
    if unit == "samples_mountain":
        return float(snap["samples_mountain"])
    if unit == "starlink_networks":
        return float(snap.get("starlink_networks") or 0)
    if unit == "flipper_networks":
        return float(snap.get("flipper_networks") or 0)
    if unit == "segments_explored":
        return float(snap.get("segments_explored") or 0)
    return 0.0


def evaluate_achievements(user_id: int) -> list[dict[str, Any]]:
    ensure_achievements_schema()
    snap = _progress_snapshot(user_id)
    newly: list[dict[str, Any]] = []
    conn = connect()
    try:
        with conn.cursor() as cur:
            for ach in CATALOG:
                for tier in ach["tiers"]:
                    key = (ach["id"], int(tier["tier"]))
                    if key in snap["unlocked"]:
                        continue
                    # Gate special-device unlocks when anomaly alerts are off
                    if tier["unit"] in {"starlink_networks", "flipper_networks"} and not snap.get(
                        tier["unit"]
                    ):
                        continue
                    val = _metric_value(snap, tier["unit"])
                    if val + 1e-9 >= float(tier["threshold"]):
                        cur.execute(
                            """
                            INSERT INTO user_achievements (user_id, achievement_id, tier, meta)
                            VALUES (%s, %s, %s, %s::jsonb)
                            ON CONFLICT DO NOTHING
                            """,
                            (
                                user_id,
                                ach["id"],
                                int(tier["tier"]),
                                f'{{"value": {val}}}',
                            ),
                        )
                        if cur.rowcount:
                            is_master = bool(tier.get("master")) or int(
                                tier["tier"]
                            ) >= len(ach["tiers"])
                            newly.append(
                                {
                                    "id": ach["id"],
                                    "tier": int(tier["tier"]),
                                    "title": tier.get("title") or ach["title"],
                                    "description": ach["description"],
                                    "flavour": ach.get("flavour"),
                                    "xp": int(tier.get("xp") or 0),
                                    "mastered": is_master,
                                    "status_label": "Mastered" if is_master else "Unlocked",
                                }
                            )
        conn.commit()
    finally:
        conn.close()
    return newly


def maybe_evaluate_achievements(
    user_id: int, min_interval_s: float | None = None
) -> list[dict[str, Any]]:
    """evaluate_achievements at most once per interval per user (hot paths)."""
    interval = ACH_EVAL_MIN_INTERVAL_S if min_interval_s is None else min_interval_s
    now = time.monotonic()
    with _eval_lock:
        if now - _last_eval_at.get(user_id, -1e9) < interval:
            return []
        _last_eval_at[user_id] = now
    return evaluate_achievements(user_id)


def _toast_payload(achievement_id: str, tier_n: int) -> dict[str, Any] | None:
    for ach in CATALOG:
        if ach["id"] != achievement_id:
            continue
        for tier in ach["tiers"]:
            if int(tier["tier"]) != tier_n:
                continue
            is_master = bool(tier.get("master")) or tier_n >= len(ach["tiers"])
            return {
                "id": ach["id"],
                "tier": tier_n,
                "title": tier.get("title") or ach["title"],
                "description": ach["description"],
                "flavour": ach.get("flavour"),
                "xp": int(tier.get("xp") or 0),
                "mastered": is_master,
                "status_label": "Mastered" if is_master else "Unlocked",
            }
    return None


def pop_unnotified(user_id: int) -> list[dict[str, Any]]:
    """Unlocks not yet shown to the user (from any thread); marks them shown."""
    ensure_achievements_schema()
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_achievements SET notified_at = NOW()
                WHERE user_id = %s AND notified_at IS NULL
                RETURNING achievement_id, tier
                """,
                (user_id,),
            )
            rows = cur.fetchall() or []
        conn.commit()
    finally:
        conn.close()
    out = []
    for achievement_id, tier_n in sorted(rows, key=lambda r: (r[0], int(r[1]))):
        payload = _toast_payload(achievement_id, int(tier_n))
        if payload:
            out.append(payload)
    return out


def list_achievements(user_id: int) -> dict[str, Any]:
    ensure_achievements_schema()
    newly = evaluate_achievements(user_id)
    snap = _progress_snapshot(user_id)
    out = []
    xp_earned = 0
    xp_available = 0
    for ach in CATALOG:
        tiers_out = []
        n_tiers = len(ach["tiers"])
        for tier in ach["tiers"]:
            key = (ach["id"], int(tier["tier"]))
            unlocked = key in snap["unlocked"]
            val = _metric_value(snap, tier["unit"])
            thr = float(tier["threshold"])
            xp = int(tier.get("xp") or 0)
            xp_available += xp
            if unlocked:
                xp_earned += xp
            unit = tier["unit"]
            unit_label = tier.get("unit_label") or _unit_label(unit)
            how = _how_for_tier(unit, thr, tier.get("how"))
            is_master = bool(tier.get("master")) or int(tier["tier"]) >= n_tiers
            mastered = bool(unlocked and is_master)
            tiers_out.append(
                {
                    "tier": int(tier["tier"]),
                    "title": tier.get("title") or ach["title"],
                    "threshold": thr,
                    "unit": unit,
                    "unit_label": unit_label,
                    "how": how,
                    "xp": xp,
                    "progress": min(val, thr) if thr else val,
                    "progress_raw": val,
                    "unlocked": unlocked,
                    "is_master_tier": is_master,
                    "mastered": mastered,
                    "status_label": (
                        "Mastered" if mastered else ("Unlocked" if unlocked else "Locked")
                    ),
                    "unlocked_at": (
                        snap["unlocked"][key]["unlocked_at"].isoformat()
                        if unlocked and snap["unlocked"][key].get("unlocked_at")
                        else None
                    ),
                }
            )
        out.append(
            {
                "id": ach["id"],
                "title": ach["title"],
                "description": ach["description"],
                "flavour": ach.get("flavour"),
                "tiers": tiers_out,
                "mastered": bool(tiers_out and tiers_out[-1].get("mastered")),
            }
        )
    activity = activity_xp_breakdown(snap, achievements_xp=xp_earned)
    xp_total = int(activity["grand_total"])
    progress = explorer_progress_from_xp(xp_total)
    progress["xp_achievements"] = xp_earned
    progress["xp_activity"] = activity
    progress["breakdown"] = activity["breakdown"]
    return {
        "timezone": ACHIEVEMENTS_TZ,
        "xp_earned": xp_earned,
        "xp_activity": activity,
        "xp_total": xp_total,
        "xp_available": xp_available,
        "explorer": progress,
        "breakdown": activity["breakdown"],
        "snapshot": {
            "km_night_total": snap["km_night_total"],
            "km_day_best": snap["km_day_best"],
            "km_today": snap["km_today"],
            "km_driven_total": snap.get("km_driven_total") or 0,
            "networks_total": snap["networks_total"],
            "networks_wifi": snap.get("networks_wifi") or 0,
            "networks_bt": snap.get("networks_bt") or 0,
            "networks_ble": snap.get("networks_ble") or 0,
            "samples_below_sea": snap["samples_below_sea"],
            "samples_mountain": snap["samples_mountain"],
            "starlink_networks": snap.get("starlink_networks") or 0,
            "flipper_networks": snap.get("flipper_networks") or 0,
            "segments_explored": snap.get("segments_explored") or 0,
            "tiles_revisited": snap.get("tiles_revisited") or 0,
            "today": snap["today"],
        },
        "achievements": out,
        "newly_unlocked": newly,
    }


def xp_for_level(level: int) -> int:
    """Cumulative XP required to *reach* level L (L>=1). Level 1 = 0 XP."""
    L = max(1, int(level))
    if L <= 1:
        return 0
    # Mild quadratic: sum_{i=1}^{L-1} 100*i = 100 * (L-1)*L/2
    return int(100 * (L - 1) * L // 2)


def level_from_xp(xp: int) -> int:
    """Largest L such that xp_for_level(L) <= xp."""
    xp = max(0, int(xp or 0))
    level = 1
    while xp_for_level(level + 1) <= xp:
        level += 1
        if level > 500:
            break
    return level


def explorer_progress_from_xp(xp: int) -> dict[str, Any]:
    xp = max(0, int(xp or 0))
    level = level_from_xp(xp)
    floor = xp_for_level(level)
    ceiling = xp_for_level(level + 1)
    into = xp - floor
    need = max(1, ceiling - floor)
    return {
        "xp": xp,
        "level": level,
        "xp_into_level": into,
        "xp_to_next": max(0, ceiling - xp),
        "xp_level_floor": floor,
        "xp_level_ceiling": ceiling,
        "progress_pct": min(100.0, round(100.0 * into / need, 1)),
        "curve": "100 * L * (L+1) / 2 cumulative to reach L+1",
    }


def explorer_progress(user_id: int) -> dict[str, Any]:
    """
    Explorer level from achievement unlocks + activity XP
    (Wi-Fi / BT / BLE finds, new/old fog tiles).
    """
    ensure_achievements_schema()
    snap = _progress_snapshot(user_id)
    ach_xp = _achievement_xp_earned(snap)
    activity = activity_xp_breakdown(snap, achievements_xp=ach_xp)
    prog = explorer_progress_from_xp(int(activity["grand_total"]))
    prog["xp_achievements"] = ach_xp
    prog["xp_activity"] = activity
    prog["breakdown"] = activity["breakdown"]
    return prog
