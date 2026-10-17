"""
Achievement catalog + progress (see docs/achievement.md).
"""

from __future__ import annotations

import math
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from db import connect, connect_dict

ACHIEVEMENTS_TZ = os.getenv("ACHIEVEMENTS_TZ") or os.getenv("STATS_TZ") or "Europe/Berlin"

# Max metres credited between two fixes (anti-teleport)
_MAX_STEP_M = 250.0
# Ignore gaps longer than this between fixes
_MAX_GAP_S = 120.0

# Activity XP (on top of achievement unlock XP) — networks pay most, distance a little
XP_PER_WIFI_NET = 5
XP_PER_BT_NET = 4
XP_PER_BLE_NET = 3
# 1 XP per 250 m driven (~4 XP / km)
XP_PER_DRIVEN_M = 1.0 / 250.0

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
    return ""


def _how_for_tier(unit: str, threshold: float | int, override: str | None = None) -> str:
    if override:
        return override
    t = _fmt_threshold(threshold)
    if unit == "km_night_total":
        return f"Drive {t} km between 00:00–06:00"
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
    return f"Reach {t}"


CATALOG: list[dict[str, Any]] = [
    {
        "id": "night_owl",
        "title": "Night owl",
        "description": "Drive between 00:00 and 06:00 local time.",
        "flavour": "The APs never sleep. Neither do you.",
        "tiers": [
            {"tier": 1, "threshold": 50.0, "unit": "km_night_total", "title": "Night owl", "xp": 100},
            {"tier": 2, "threshold": 200.0, "unit": "km_night_total", "title": "Night owl II", "xp": 250},
            {"tier": 3, "threshold": 500.0, "unit": "km_night_total", "title": "Night owl III", "xp": 600},
        ],
    },
    {
        "id": "memelord",
        "title": "Memelord",
        "description": "Drive a meme distance in a single calendar day.",
        "flavour": "42 → 67 → 133.7. Respect the lore.",
        "tiers": [
            {"tier": 1, "threshold": 42.0, "unit": "km_day_best", "title": "Memelord", "xp": 150},
            {"tier": 2, "threshold": 67.0, "unit": "km_day_best", "title": "Memelord II", "xp": 300},
            {"tier": 3, "threshold": 133.7, "unit": "km_day_best", "title": "Memelord III", "xp": 700},
        ],
    },
    {
        "id": "hack_all_the_things",
        "title": "Hack all the things",
        "description": "Collect triangulated networks in your local database.",
        "flavour": "More boxes. More packets. More everything.",
        "tiers": [
            {
                "tier": 1,
                "threshold": 50_000,
                "unit": "networks_total",
                "title": "Hack all the things",
                "xp": 200,
            },
            {
                "tier": 2,
                "threshold": 200_000,
                "unit": "networks_total",
                "title": "Hack all the things II",
                "xp": 500,
            },
            {
                "tier": 3,
                "threshold": 500_000,
                "unit": "networks_total",
                "title": "Hack all the things III",
                "xp": 1200,
            },
        ],
    },
    {
        "id": "aden_pierce",
        "title": "Aden Pierce",
        "description": "Collect one million triangulated networks.",
        "flavour": "ctOS would be proud. Probably.",
        "tiers": [
            {
                "tier": 1,
                "threshold": 1_000_000,
                "unit": "networks_total",
                "title": "Aden Pierce",
                "xp": 2500,
            },
        ],
    },
    {
        "id": "below_sea",
        "title": "Below sea",
        "description": "Collect observation points with GPS altitude below 0 m.",
        "flavour": "Dead reckoning in the bathyscape.",
        "tiers": [
            {
                "tier": 1,
                "threshold": 500,
                "unit": "samples_below_sea",
                "title": "Below sea",
                "xp": 200,
            },
        ],
    },
    {
        "id": "mountainclimber",
        "title": "Mountainclimber",
        "description": "Collect observation points with GPS altitude above 700 m.",
        "flavour": "Thin air, thick RF.",
        "tiers": [
            {
                "tier": 1,
                "threshold": 500,
                "unit": "samples_mountain",
                "title": "Mountainclimber",
                "xp": 200,
            },
        ],
    },
    {
        "id": "transmitting_to_space",
        "title": "Transmitting to space",
        "description": "Detect distinct Starlink user Wi‑Fi hotspots (default STARLINK SSID).",
        "flavour": "Low Earth orbit, high RSSI envy.",
        "tiers": [
            {
                "tier": 1,
                "threshold": 10,
                "unit": "starlink_networks",
                "title": "Transmitting to space",
                "xp": 150,
            },
            {
                "tier": 2,
                "threshold": 50,
                "unit": "starlink_networks",
                "title": "Transmitting to space II",
                "xp": 400,
            },
            {
                "tier": 3,
                "threshold": 100,
                "unit": "starlink_networks",
                "title": "Transmitting to space III",
                "xp": 900,
            },
        ],
    },
]


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(ACHIEVEMENTS_TZ)
    except Exception:
        return ZoneInfo("UTC")


def ensure_achievements_schema() -> None:
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
        conn.commit()
    finally:
        conn.close()


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def record_drive_step(
    user_id: int,
    *,
    lat: float,
    lon: float,
    prev_lat: float | None,
    prev_lon: float | None,
    prev_ts: float | None,
    now_ts: float | None = None,
    explored_km_delta: float = 0.0,
) -> dict[str, Any]:
    """
    Credit distance between consecutive fixes. Returns day counters + any new unlocks.
    """
    ensure_achievements_schema()
    tz = _tz()
    now = datetime.fromtimestamp(now_ts or datetime.now(tz=tz).timestamp(), tz=tz)
    day = now.date()
    hour = now.hour
    is_night = 0 <= hour < 6

    added_km = 0.0
    if (
        prev_lat is not None
        and prev_lon is not None
        and prev_ts is not None
        and now_ts is not None
        and 0 < (now_ts - prev_ts) <= _MAX_GAP_S
    ):
        step_m = _haversine_m(prev_lat, prev_lon, lat, lon)
        if step_m <= _MAX_STEP_M:
            added_km = step_m / 1000.0

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
                    max(0.0, float(explored_km_delta or 0)),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    newly = evaluate_achievements(user_id)
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
                    WHERE upper(coalesce(network_type, '')) IN ('WIFI', 'W', 'WLAN', '802.11')
                  )::int AS wifi,
                  COUNT(*) FILTER (
                    WHERE upper(coalesce(network_type, '')) IN ('BT', 'BLUETOOTH', 'BR/EDR')
                  )::int AS bt,
                  COUNT(*) FILTER (
                    WHERE upper(coalesce(network_type, '')) IN ('BLE', 'BTLE')
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
            cur.execute(
                """
                SELECT COALESCE(SUM(km_total), 0)::float AS km_driven_total
                FROM drive_day_km WHERE user_id = %s
                """,
                (user_id,),
            )
            km_driven_total = float((cur.fetchone() or {}).get("km_driven_total") or 0)
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
    finally:
        conn.close()

    # Starlink progress only when special detections are enabled (see docs/anomalies.md)
    starlink_networks = 0
    try:
        from anomalies import anomaly_alerts_enabled, count_starlink_networks

        if anomaly_alerts_enabled(user_id):
            starlink_networks = count_starlink_networks(user_id)
    except Exception:
        starlink_networks = 0

    unlocked = {(r["achievement_id"], int(r["tier"])): r for r in unlocked_rows}
    return {
        "km_night_total": float(agg.get("km_night_total") or 0),
        "km_day_best": float(agg.get("km_day_best") or 0),
        "km_today": float(today_row.get("km_total") or 0),
        "km_night_today": float(today_row.get("km_night") or 0),
        "km_driven_total": km_driven_total,
        "networks_total": networks_total,
        "networks_wifi": networks_wifi,
        "networks_bt": networks_bt,
        "networks_ble": networks_ble,
        "samples_below_sea": samples_below_sea,
        "samples_mountain": samples_mountain,
        "starlink_networks": starlink_networks,
        "unlocked": unlocked,
        "today": today.isoformat(),
    }


def activity_xp_breakdown(snap: dict[str, Any]) -> dict[str, Any]:
    """XP from discovered networks + driven distance (deterministic from inventory)."""
    wifi = int(snap.get("networks_wifi") or 0)
    bt = int(snap.get("networks_bt") or 0)
    ble = int(snap.get("networks_ble") or 0)
    meters = float(snap.get("km_driven_total") or 0) * 1000.0
    from_wifi = wifi * XP_PER_WIFI_NET
    from_bt = bt * XP_PER_BT_NET
    from_ble = ble * XP_PER_BLE_NET
    from_drive = int(meters * XP_PER_DRIVEN_M)
    return {
        "wifi": from_wifi,
        "bt": from_bt,
        "ble": from_ble,
        "driven": from_drive,
        "total": from_wifi + from_bt + from_ble + from_drive,
        "counts": {"wifi": wifi, "bt": bt, "ble": ble, "km": round(meters / 1000.0, 3)},
        "rates": {
            "wifi": XP_PER_WIFI_NET,
            "bt": XP_PER_BT_NET,
            "ble": XP_PER_BLE_NET,
            "driven_m_per_xp": round(1.0 / XP_PER_DRIVEN_M),
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
                    # Gate Starlink unlocks when special detections are off
                    if tier["unit"] == "starlink_networks" and not snap.get(
                        "starlink_networks"
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
                            newly.append(
                                {
                                    "id": ach["id"],
                                    "tier": int(tier["tier"]),
                                    "title": tier.get("title") or ach["title"],
                                    "description": ach["description"],
                                    "flavour": ach.get("flavour"),
                                    "xp": int(tier.get("xp") or 0),
                                }
                            )
        conn.commit()
    finally:
        conn.close()
    return newly


def list_achievements(user_id: int) -> dict[str, Any]:
    ensure_achievements_schema()
    newly = evaluate_achievements(user_id)
    snap = _progress_snapshot(user_id)
    out = []
    xp_earned = 0
    xp_available = 0
    for ach in CATALOG:
        tiers_out = []
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
            }
        )
    activity = activity_xp_breakdown(snap)
    xp_total = xp_earned + int(activity["total"])
    progress = explorer_progress_from_xp(xp_total)
    progress["xp_achievements"] = xp_earned
    progress["xp_activity"] = activity
    return {
        "timezone": ACHIEVEMENTS_TZ,
        "xp_earned": xp_earned,
        "xp_activity": activity,
        "xp_total": xp_total,
        "xp_available": xp_available,
        "explorer": progress,
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
    (Wi‑Fi / BT / BLE finds and a little from driven metres).
    """
    ensure_achievements_schema()
    snap = _progress_snapshot(user_id)
    ach_xp = _achievement_xp_earned(snap)
    activity = activity_xp_breakdown(snap)
    prog = explorer_progress_from_xp(ach_xp + int(activity["total"]))
    prog["xp_achievements"] = ach_xp
    prog["xp_activity"] = activity
    return prog
