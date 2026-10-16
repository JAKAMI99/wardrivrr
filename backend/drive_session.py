"""Session counters for the drive HUD (radio captures since spawn)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db import connect_dict

_EMPTY = {
    "wifi": {"seen": 0, "new": 0},
    "bt": {"seen": 0, "new": 0},
    "ble": {"seen": 0, "new": 0},
}


def _bucket(nt: str | None) -> str | None:
    t = (nt or "").strip().upper()
    if t in {"WIFI", "W", "WLAN", "802.11"}:
        return "wifi"
    if t in {"BLE", "BTLE"}:
        return "ble"
    if t in {"BT", "BLUETOOTH", "BR/EDR"}:
        return "bt"
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
                    out[key]["seen"] = int(row["n"] or 0)

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
                    out[key]["new"] = int(row["n"] or 0)
    finally:
        conn.close()
    return out
