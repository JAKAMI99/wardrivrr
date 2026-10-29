from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from db import connect_dict

# Explorer timezone for "today" / streaks (override with STATS_TZ).
STATS_TZ = os.getenv("STATS_TZ", "Europe/Berlin")


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(STATS_TZ)
    except Exception:
        return ZoneInfo("UTC")


def _day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start_local = datetime(day.year, day.month, day.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _period_counts(
    cur,
    start_utc: datetime | None,
    end_utc: datetime | None,
    user_id: int | None = None,
) -> dict:
    """Counts for networks first seen / samples seen in [start, end)."""
    net_params: list = []
    samp_params: list = []
    net_sql = """
        SELECT COUNT(*) AS n,
               COUNT(*) FILTER (WHERE upper(network_type)='WIFI') AS wifi,
               COUNT(*) FILTER (WHERE upper(network_type)='BT') AS bt,
               COUNT(*) FILTER (WHERE upper(network_type)='BLE') AS ble
        FROM networks WHERE 1=1
    """
    samp_sql = "SELECT COUNT(*) AS n FROM signal_samples WHERE 1=1"
    if user_id is not None:
        net_sql += " AND user_id = %s"
        samp_sql += " AND user_id = %s"
        net_params.append(user_id)
        samp_params.append(user_id)
    if start_utc is not None:
        net_sql += " AND first_seen >= %s"
        samp_sql += " AND seen_at >= %s"
        net_params.append(start_utc)
        samp_params.append(start_utc)
    if end_utc is not None:
        net_sql += " AND first_seen < %s"
        samp_sql += " AND seen_at < %s"
        net_params.append(end_utc)
        samp_params.append(end_utc)

    cur.execute(net_sql, net_params)
    net = cur.fetchone()
    cur.execute(samp_sql, samp_params)
    samp = cur.fetchone()
    return {
        "networks": net["n"],
        "wifi": net["wifi"],
        "bt": net["bt"],
        "ble": net["ble"],
        "samples": samp["n"],
    }


def _milestone(current: int) -> dict:
    """Next round milestone (competence + goal-gradient)."""
    ladders = [
        10,
        25,
        50,
        100,
        250,
        500,
        1000,
        2500,
        5000,
        10000,
        25000,
        50000,
        100000,
    ]
    target = next((n for n in ladders if n > current), ((current // 100000) + 1) * 100000)
    prev = 0
    for n in ladders:
        if n >= target:
            break
        prev = n
    if target not in ladders:
        prev = (current // 100000) * 100000
    span = max(target - prev, 1)
    progress = min(max(current - prev, 0) / span, 1.0)
    return {
        "current": current,
        "previous": prev,
        "next": target,
        "remaining": max(target - current, 0),
        "progress": round(progress, 4),
    }


def _compute_streak(active_days: list[date], today: date) -> dict:
    """Consecutive calendar days ending today or yesterday (grace for late night)."""
    if not active_days:
        return {"current": 0, "best": 0, "active_today": False, "grace": False}

    day_set = set(active_days)
    best = 0
    run = 0
    # best streak across history
    cursor = None
    for d in sorted(day_set):
        if cursor is not None and d == cursor + timedelta(days=1):
            run += 1
        else:
            run = 1
        best = max(best, run)
        cursor = d

    active_today = today in day_set
    # Allow streak to continue if yesterday was active (grace) even if today quiet so far
    start = today if active_today else today - timedelta(days=1)
    grace = (not active_today) and (start in day_set)
    current = 0
    d = start
    while d in day_set:
        current += 1
        d -= timedelta(days=1)

    return {
        "current": current,
        "best": best,
        "active_today": active_today,
        "grace": grace,
    }


def _motivation(today: dict, yesterday: dict, streak: dict, wifi_all: int) -> dict:
    """Light copy for competence / goal-gradient — no shame on zero days."""
    headlines = []
    if today["networks"] > 0:
        headlines.append(f"+{today['networks']} new networks today")
    elif streak["grace"]:
        headlines.append("Streak still warm — one find keeps it alive")
    elif streak["current"] > 0:
        headlines.append(f"{streak['current']}-day streak · keep exploring")
    else:
        headlines.append("Fresh day · first network starts the streak")

    delta = today["networks"] - yesterday["networks"]
    if yesterday["networks"] > 0 and today["networks"] > yesterday["networks"]:
        nudge = f"Ahead of yesterday by {delta}"
    elif yesterday["networks"] > 0 and today["networks"] == 0:
        nudge = f"Yesterday you found {yesterday['networks']} — today's board is open"
    elif today["networks"] > 0:
        nudge = "Momentum is building"
    else:
        nudge = "Autonomy tip: pick a quiet street or a busy plaza — your call"

    mile = _milestone(wifi_all)
    if mile["remaining"] <= 25 and mile["remaining"] > 0:
        nudge = f"Goal gradient: only {mile['remaining']} Wi‑Fi to {mile['next']:,}"

    return {
        "headline": headlines[0],
        "nudge": nudge,
        "science": [
            "Competence: clear progress toward the next milestone",
            "Autonomy: you choose when and how to explore",
            "Goal gradient: effort rises as you near a finish line",
            "Streaks: optional continuity — grace if today is still open",
        ],
    }


def build_stats_dashboard(user_id: int | None = None) -> dict:
    tz = _tz()
    now_local = datetime.now(tz)
    today = now_local.date()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=6)

    today_start, today_end = _day_bounds(today, tz)
    y_start, y_end = _day_bounds(yesterday, tz)
    week_start_utc, _ = _day_bounds(week_start, tz)

    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            today_c = _period_counts(cur, today_start, today_end, user_id)
            yest_c = _period_counts(cur, y_start, y_end, user_id)
            week_c = _period_counts(cur, week_start_utc, today_end, user_id)
            all_c = _period_counts(cur, None, None, user_id)

            user_clause = " AND user_id = %s" if user_id is not None else ""
            user_params: list = [STATS_TZ] + ([user_id] if user_id is not None else [])

            cur.execute(
                f"""
                SELECT DISTINCT (first_seen AT TIME ZONE %s)::date AS d
                FROM networks
                WHERE first_seen IS NOT NULL{user_clause}
                ORDER BY 1 DESC
                LIMIT 400
                """,
                user_params,
            )
            active_days = [row["d"] for row in cur.fetchall() if row["d"] is not None]

            cur.execute(
                f"""
                SELECT (first_seen AT TIME ZONE %s)::date AS d, COUNT(*) AS n
                FROM networks
                WHERE first_seen IS NOT NULL{user_clause}
                GROUP BY 1
                ORDER BY n DESC
                LIMIT 1
                """,
                user_params,
            )
            best_day = cur.fetchone()

            if user_id is not None:
                cur.execute(
                    """
                    SELECT MIN(first_seen) AS first_seen, MAX(last_seen) AS last_seen
                    FROM networks WHERE user_id = %s
                    """,
                    (user_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT MIN(first_seen) AS first_seen, MAX(last_seen) AS last_seen
                    FROM networks
                    """
                )
            span = cur.fetchone()
    finally:
        conn.close()

    streak = _compute_streak(active_days, today)
    wifi_mile = _milestone(all_c["wifi"])
    net_mile = _milestone(all_c["networks"])

    return {
        "timezone": STATS_TZ,
        "as_of": now_local.isoformat(),
        "today": today_c,
        "yesterday": yest_c,
        "week": week_c,
        "all_time": all_c,
        "streak": streak,
        "milestones": {
            "wifi": wifi_mile,
            "networks": net_mile,
        },
        "personal_best": {
            "best_day": str(best_day["d"]) if best_day and best_day["d"] else None,
            "best_day_networks": best_day["n"] if best_day else 0,
        },
        "span": {
            "first_seen": _iso(span["first_seen"]) if span else None,
            "last_seen": _iso(span["last_seen"]) if span else None,
        },
        "motivation": _motivation(today_c, yest_c, streak, all_c["wifi"]),
        "xp": {
            "enabled": False,
            "note": "XP and levels land next — numbers here already fuel the loop.",
        },
    }
