"""
Special-device / Easter-egg anomaly matching for drive mode.

Rules live in anomaly_rules.json (data-driven). Flipper detection follows
Wall of Flippers (k3yomi/Wall-of-Flippers): Flipper Devices Inc MAC OUIs
80:e1:26 / 80:e1:27 / 0c:fa:22, or a BLE name starting with \"flipper\".
Service UUID identifiers are not available in our stored samples.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

_RULES_PATH = Path(__file__).with_name("anomaly_rules.json")

_MAC_RE = re.compile(r"[^0-9a-f]")


def _norm_mac(raw: str | None) -> str:
    if not raw:
        return ""
    return _MAC_RE.sub("", str(raw).lower())


def _mac_colons(norm: str) -> str:
    if len(norm) < 12:
        return norm
    return ":".join(norm[i : i + 2] for i in range(0, 12, 2))


def _norm_type(raw: str | None) -> str:
    t = (raw or "").strip().upper()
    if t in {"WIFI", "W", "WLAN", "802.11"}:
        return "WIFI"
    if t in {"BLE", "BTLE"}:
        return "BLE"
    if t in {"BT", "BLUETOOTH", "BR/EDR"}:
        return "BT"
    return t


@lru_cache(maxsize=1)
def load_rules() -> list[dict[str, Any]]:
    data = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
    rules = list(data.get("rules") or [])
    rules.sort(key=lambda r: int(r.get("priority") or 0), reverse=True)
    return rules


def reload_rules() -> list[dict[str, Any]]:
    load_rules.cache_clear()
    return load_rules()


def anomaly_alerts_enabled(user_id: int) -> bool:
    from db import get_user_setting

    raw = get_user_setting(user_id, "anomaly_alerts", "true") or "true"
    return str(raw).lower() in {"1", "true", "yes", "on"}


def match_network(
    *,
    network_id: str | None,
    name: str | None,
    network_type: str | None,
    rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Return the highest-priority matching rule, or None."""
    mac = _norm_mac(network_id)
    mac_colon = _mac_colons(mac) if len(mac) >= 12 else ""
    ssid = (name or "").strip()
    ssid_l = ssid.lower()
    ntype = _norm_type(network_type)

    for rule in rules or load_rules():
        types = [str(t).upper() for t in (rule.get("network_types") or [])]
        if types and ntype not in types:
            continue

        hit = False

        for exact in rule.get("mac_exact") or []:
            if mac and mac == _norm_mac(exact):
                hit = True
                break

        if not hit:
            for prefix in rule.get("mac_prefixes") or []:
                p = _norm_mac(prefix)
                if p and mac.startswith(p):
                    hit = True
                    break

        if not hit and rule.get("mac_byte12"):
            # Match bytes [1] and [2] as 13:37 → positions 2..6 of colon form
            needle = str(rule["mac_byte12"]).lower().replace("-", ":")
            if mac_colon and len(mac_colon) >= 8 and mac_colon[3:8] == needle:
                hit = True

        if not hit:
            for pref in rule.get("name_prefixes") or []:
                if ssid_l.startswith(str(pref).lower()):
                    hit = True
                    break

        if not hit:
            for exact in rule.get("ssid_exact") or []:
                if ssid_l == str(exact).lower():
                    hit = True
                    break

        if not hit:
            for pref in rule.get("ssid_prefixes") or []:
                if ssid_l.startswith(str(pref).lower()):
                    hit = True
                    break

        if not hit:
            for frag in rule.get("name_contains_any") or []:
                if frag and frag.lower() in ssid_l:
                    hit = True
                    break

        if hit:
            return {
                "id": rule["id"],
                "title": rule.get("title") or rule["id"],
                "toast": rule.get("toast") or rule.get("title") or rule["id"],
                "flavour": rule.get("flavour") or "",
                "sound": rule.get("sound") or "blip",
                "network_id": network_id,
                "name": name,
                "network_type": ntype,
                "counts_for": rule.get("counts_for"),
            }
    return None


def count_networks_for(user_id: int, counts_for: str) -> int:
    """Distinct user networks matching rules with the given counts_for key."""
    from db import connect_dict

    rules = [r for r in load_rules() if r.get("counts_for") == counts_for]
    if not rules:
        return 0

    type_set: set[str] = set()
    for rule in rules:
        for t in rule.get("network_types") or []:
            type_set.add(str(t).upper())

    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            if counts_for == "starlink_networks":
                cur.execute(
                    """
                    SELECT network_id, name, network_type
                    FROM networks
                    WHERE user_id = %s
                      AND name IS NOT NULL
                      AND (
                        upper(btrim(name)) = 'STARLINK'
                        OR upper(btrim(name)) LIKE 'STARLINK-%%'
                      )
                    """,
                    (user_id,),
                )
            elif counts_for == "flipper_networks":
                # Include type aliases; match_network does the real fingerprinting.
                cur.execute(
                    """
                    SELECT network_id, name, network_type
                    FROM networks
                    WHERE user_id = %s
                      AND (
                        upper(btrim(COALESCE(network_type, '')))
                          IN ('BT', 'BLE', 'BTLE', 'BLUETOOTH', 'BR/EDR')
                        OR lower(COALESCE(name, '')) LIKE 'flipper%%'
                      )
                    """,
                    (user_id,),
                )
            elif type_set:
                cur.execute(
                    """
                    SELECT network_id, name, network_type
                    FROM networks
                    WHERE user_id = %s
                      AND upper(btrim(COALESCE(network_type, ''))) = ANY(%s)
                    """,
                    (user_id, list(type_set)),
                )
            else:
                cur.execute(
                    """
                    SELECT network_id, name, network_type
                    FROM networks
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
            rows = cur.fetchall() or []
    finally:
        conn.close()

    n = 0
    for row in rows:
        if match_network(
            network_id=row.get("network_id"),
            name=row.get("name"),
            network_type=row.get("network_type"),
            rules=rules,
        ):
            n += 1
    return n


def count_starlink_networks(user_id: int) -> int:
    """Distinct user networks matching Starlink SSID rules."""
    return count_networks_for(user_id, "starlink_networks")


def count_flipper_networks(user_id: int) -> int:
    """Distinct Flipper Zero BT/BLE devices (Wall of Flippers fingerprints)."""
    return count_networks_for(user_id, "flipper_networks")


def session_anomaly_hits(user_id: int, since: datetime) -> list[dict[str, Any]]:
    """
    Networks observed this drive session that match anomaly rules.
    Uses distinct network_ids from signal_samples since `since`, joined to
    networks for name/type when available.
    """
    if not anomaly_alerts_enabled(user_id):
        return []

    from db import connect_dict

    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  s.network_id,
                  MAX(COALESCE(n.name, s.name)) AS name,
                  MAX(COALESCE(n.network_type, s.network_type)) AS network_type
                FROM signal_samples s
                LEFT JOIN networks n
                  ON n.user_id = s.user_id AND n.network_id = s.network_id
                WHERE s.user_id = %s
                  AND s.seen_at >= %s
                  AND s.network_id IS NOT NULL
                GROUP BY s.network_id
                """,
                (user_id, since),
            )
            rows = cur.fetchall() or []
    finally:
        conn.close()

    priority = {r["id"]: int(r.get("priority") or 0) for r in load_rules()}
    hits: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in rows:
        m = match_network(
            network_id=row.get("network_id"),
            name=row.get("name"),
            network_type=row.get("network_type"),
        )
        if not m:
            continue
        key = f"{m['id']}:{_norm_mac(m.get('network_id'))}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        hits.append(m)
    hits.sort(key=lambda h: (-priority.get(h["id"], 0), h["id"]))
    return hits
