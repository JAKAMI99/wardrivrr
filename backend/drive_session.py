"""Session counters for the drive HUD (radio captures since spawn)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from db import connect_dict

_EMPTY = {
    "wifi": {"seen": 0, "new": 0},
    "bt": {"seen": 0, "new": 0},
    "ble": {"seen": 0, "new": 0},
}


def _bucket(nt: str | None) -> str | None:
    t = (nt or "").strip().upper()
    if not t:
        return None
    if t in {"BLE", "BTLE"} or "BLE" in t or "BTLE" in t:
        return "ble"
    if t in {"BT", "BLUETOOTH", "BR/EDR"} or (
        "BT" in t and "BLE" not in t and "BTLE" not in t
    ):
        return "bt"
    if (
        t in {"WIFI", "W", "WLAN", "802.11", "IEEE802.11", "WI-FI"}
        or "WIFI" in t
        or "802.11" in t
        or "WLAN" in t
    ):
        return "wifi"
    return None


def parse_session_start(raw: str | None) -> datetime | None:
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def session_radio_stats(user_id: int, since: datetime) -> dict[str, Any]:
    """
    seen = distinct networks with a sample since `since`
    new  = networks whose first_seen is since `since`
    """
    out = {k: dict(v) for k, v in _EMPTY.items()}
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT network_type, COUNT(DISTINCT network_id)::int AS n
                FROM signal_samples
                WHERE user_id = %s AND seen_at >= %s AND network_id IS NOT NULL
                GROUP BY network_type
                """,
                (user_id, since),
            )
            for row in cur.fetchall() or []:
                key = _bucket(row.get("network_type"))
                if key:
                    out[key]["seen"] += int(row["n"] or 0)

            # "new" = first time we saw this network in this session
            # (works even before localize has upserted networks rows)
            cur.execute(
                """
                SELECT s.network_type, COUNT(DISTINCT s.network_id)::int AS n
                FROM signal_samples s
                LEFT JOIN networks n
                  ON n.user_id = s.user_id AND n.network_id = s.network_id
                WHERE s.user_id = %s
                  AND s.seen_at >= %s
                  AND s.network_id IS NOT NULL
                  AND (n.network_id IS NULL OR n.first_seen IS NULL OR n.first_seen >= %s)
                GROUP BY s.network_type
                """,
                (user_id, since, since),
            )
            for row in cur.fetchall() or []:
                key = _bucket(row.get("network_type"))
                if key:
                    out[key]["new"] += int(row["n"] or 0)
    finally:
        conn.close()
    return out


def session_recent_hits(
    user_id: int,
    window_s: float = 30.0,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """
    Distinct networks observed in the last `window_s` seconds, with GPS
    of the newest sample. Used by Drive receive-FX dots (no schema change).
    """
    since = datetime.now(timezone.utc) - timedelta(seconds=max(1.0, float(window_s)))
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM (
                  SELECT DISTINCT ON (network_id)
                    network_id,
                    name,
                    network_type,
                    lat,
                    lon,
                    seen_at
                  FROM signal_samples
                  WHERE user_id = %s
                    AND seen_at >= %s
                    AND network_id IS NOT NULL
                    AND lat IS NOT NULL
                    AND lon IS NOT NULL
                  ORDER BY network_id, seen_at DESC
                ) recent
                ORDER BY seen_at DESC
                LIMIT %s
                """,
                (user_id, since, int(limit)),
            )
            rows = cur.fetchall() or []
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (TypeError, ValueError):
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        seen = row.get("seen_at")
        if isinstance(seen, datetime):
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            seen_iso = seen.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            seen_iso = str(seen) if seen else None
        out.append(
            {
                "network_id": row.get("network_id"),
                "name": row.get("name"),
                "network_type": row.get("network_type"),
                "lat": lat,
                "lon": lon,
                "seen_at": seen_iso,
            }
        )
    return out
