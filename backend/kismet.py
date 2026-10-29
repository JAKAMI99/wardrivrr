from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

try:
    from wigle import observation_tuple
except ImportError:
    from backend.wigle import observation_tuple


def _tables(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cur.fetchall()}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def is_kismet_db(path: Path) -> bool:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        names = _tables(conn)
        return "devices" in names
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _mac_str(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        if len(value) == 6:
            return ":".join(f"{b:02x}" for b in value)
        try:
            value = value.decode("utf-8", errors="ignore")
        except Exception:
            return None
    text = str(value).strip().lower().replace("-", ":")
    return text or None


def _ts(value) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            if ts <= 0:
                return None
            return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None
    return None


def _phy_to_type(phy: str | None, type_name: str | None = None) -> str:
    blob = f"{phy or ''} {type_name or ''}".lower()
    if "ble" in blob or "btle" in blob:
        return "BLE"
    if "bluetooth" in blob or blob.strip() in {"bt", "br/edr"}:
        return "BT"
    if "802.11" in blob or "ieee802.11" in blob or "wifi" in blob or "wlan" in blob:
        return "WIFI"
    if "lte" in blob:
        return "LTE"
    if "gsm" in blob or "cellular" in blob:
        return "GSM"
    return "WIFI"


def _dig(obj, *keys):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _parse_device_json(raw) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    if isinstance(raw, bytes):
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            try:
                import msgpack

                return msgpack.unpackb(raw, raw=False, strict_map_key=False)
            except Exception:
                return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    if isinstance(raw, dict):
        return raw
    return None


def _geopoint(loc_obj: dict | None) -> tuple[float | None, float | None, float | None]:
    if not isinstance(loc_obj, dict):
        return None, None, None
    avg = loc_obj.get("kismet.common.location.avg_loc") or loc_obj.get(
        "kismet.common.location.min_loc"
    )
    alt = None
    lat = lon = None
    if isinstance(avg, dict):
        geopoint = avg.get("kismet.common.location.geopoint")
        alt = avg.get("kismet.common.location.alt")
        if isinstance(geopoint, (list, tuple)) and len(geopoint) >= 2:
            lon, lat = float(geopoint[0]), float(geopoint[1])
    lat = loc_obj.get("kismet.common.location.avg_lat", lat)
    lon = loc_obj.get("kismet.common.location.avg_lon", lon)
    alt = loc_obj.get("kismet.common.location.avg_alt", alt) or loc_obj.get(
        "kismet.common.location.alt", alt
    )
    try:
        lat = float(lat) if lat is not None else None
        lon = float(lon) if lon is not None else None
        alt = float(alt) if alt is not None else None
    except (TypeError, ValueError):
        return None, None, None
    return lat, lon, alt


def _encryption_from_device(device: dict) -> str | None:
    """Pull Wi-Fi crypt string from Kismet device JSON (base.crypt or advertised SSID)."""
    crypt = device.get("kismet.device.base.crypt")
    if isinstance(crypt, str) and crypt.strip():
        return crypt.strip()
    dot11 = device.get("dot11.device")
    if not isinstance(dot11, dict):
        return None
    for key, val in dot11.items():
        if "advertised_ssid" not in key or not isinstance(val, dict):
            continue
        for ssidrec in val.values():
            if not isinstance(ssidrec, dict):
                continue
            cs = (
                ssidrec.get("dot11.advertisedssid.crypt_string")
                or ssidrec.get("dot11.advertisedssid.crypt_set")
            )
            if isinstance(cs, str) and cs.strip():
                return cs.strip()
            if cs:
                return str(cs)
    return None


def _device_meta_from_json(device: dict | None, row: sqlite3.Row) -> dict:
    name = None
    encryption = None
    channel = None
    phy = None
    mac = None
    signal = None
    lat = lon = alt = None
    seen = None

    if device:
        mac = _mac_str(
            _dig(device, "kismet.device.base.macaddr")
            or _dig(device, "kismet.device.base_mac")
            or _dig(device, "kismet.device.macaddr")
        )
        name = (
            _dig(device, "dot11.device", "dot11.device.last_beaconed_ssid_record", "dot11.advertisedssid.ssid")
            or _dig(device, "kismet.device.base.commonname")
            or _dig(device, "kismet.device.base.name")
            or _dig(device, "kismet.device.commonname")
            or _dig(device, "kismet.device.name")
        )
        phy = _dig(device, "kismet.device.base.phyname") or _dig(device, "kismet.device.base_phyname")
        sig = _dig(device, "kismet.device.base.signal") or _dig(device, "kismet.device.signals")
        if isinstance(sig, dict):
            signal = sig.get("kismet.common.signal.last_signal") or sig.get(
                "kismet.common.signal.max_signal"
            )
        loc = _dig(device, "kismet.device.base.location") or _dig(device, "kismet.device.location")
        lat, lon, alt = _geopoint(loc if isinstance(loc, dict) else None)
        seen = _dig(device, "kismet.device.base.last_time") or _dig(device, "kismet.device.last_time")
        channel = _dig(device, "dot11.device", "dot11.device.channel")
        encryption = _encryption_from_device(device)

    keys = set(row.keys()) if hasattr(row, "keys") else set()
    if mac is None and "devmac" in keys:
        mac = _mac_str(row["devmac"])
    if (lat is None or lat == 0) and "avg_lat" in keys and row["avg_lat"]:
        lat = row["avg_lat"]
    if (lon is None or lon == 0) and "avg_lon" in keys and row["avg_lon"]:
        lon = row["avg_lon"]
    if signal in (None, 0) and "strongest_signal" in keys and row["strongest_signal"]:
        signal = row["strongest_signal"]
    if seen is None and "last_time" in keys:
        seen = row["last_time"]
    if phy is None and "phyname" in keys:
        phy = row["phyname"]
    type_name = row["type"] if "type" in keys else None

    try:
        from wigle import sanitize_network_name
    except ImportError:
        from backend.wigle import sanitize_network_name

    return {
        "network_id": mac,
        "name": sanitize_network_name(name, mac),
        "encryption": encryption,
        "network_type": _phy_to_type(phy if isinstance(phy, str) else None, type_name),
        "channel": channel,
        "signal": signal if signal not in (0, "0") else None,
        "lat": lat,
        "lon": lon,
        "altitude": alt,
        "seen_at": _ts(seen) if not isinstance(seen, datetime) else seen,
    }


def _load_device_index(conn: sqlite3.Connection) -> dict[str, dict]:
    """Map MAC -> metadata for enriching packet samples."""
    index: dict[str, dict] = {}
    cols = _columns(conn, "devices")
    select = ["devmac", "phyname", "type", "strongest_signal", "avg_lat", "avg_lon", "last_time"]
    select = [c for c in select if c in cols]
    if "device" in cols:
        select.append("device")
    if not select:
        return index
    cur = conn.execute(f"SELECT {', '.join(select)} FROM devices")
    for row in cur:
        device = _parse_device_json(row["device"]) if "device" in cols else None
        meta = _device_meta_from_json(device, row)
        mac = meta.get("network_id")
        if mac:
            index[mac] = meta
    return index


def _append(rows_out: list, record: dict, source: str) -> None:
    tup = observation_tuple(record, source, source_format="kismet")
    if tup:
        rows_out.append(tup)


def _parse_from_packets(conn: sqlite3.Connection, source: str, device_index: dict[str, dict]) -> list[tuple]:
    cols = _columns(conn, "packets")
    needed = {"sourcemac", "lat", "lon"}
    if not needed.issubset(cols):
        return []
    fields = ["sourcemac", "lat", "lon", "ts_sec"]
    for optional in ("alt", "signal", "phyname"):
        if optional in cols:
            fields.append(optional)
    sql = f"""
        SELECT {', '.join(fields)}
        FROM packets
        WHERE lat IS NOT NULL AND lon IS NOT NULL
          AND lat != 0 AND lon != 0
          AND sourcemac IS NOT NULL AND sourcemac != ''
    """
    rows_out: list[tuple] = []
    for row in conn.execute(sql):
        mac = _mac_str(row["sourcemac"])
        if not mac:
            continue
        meta = device_index.get(mac, {})
        signal = row["signal"] if "signal" in row.keys() else None
        if signal in (0, "0"):
            signal = meta.get("signal")
        phy = row["phyname"] if "phyname" in row.keys() else None
        record = {
            "network_id": mac,
            "name": meta.get("name"),
            "encryption": meta.get("encryption"),
            "network_type": _phy_to_type(phy, None) if phy else meta.get("network_type", "WIFI"),
            "channel": meta.get("channel"),
            "signal": signal,
            "lat": row["lat"],
            "lon": row["lon"],
            "altitude": row["alt"] if "alt" in row.keys() else meta.get("altitude"),
            "seen_at": _ts(row["ts_sec"]),
            "accuracy": None,
        }
        _append(rows_out, record, source)
    return rows_out


def _parse_from_devices(conn: sqlite3.Connection, source: str, device_index: dict[str, dict]) -> list[tuple]:
    rows_out: list[tuple] = []
    for meta in device_index.values():
        record = {
            "network_id": meta.get("network_id"),
            "name": meta.get("name"),
            "encryption": meta.get("encryption"),
            "network_type": meta.get("network_type", "WIFI"),
            "channel": meta.get("channel"),
            "signal": meta.get("signal"),
            "lat": meta.get("lat"),
            "lon": meta.get("lon"),
            "altitude": meta.get("altitude"),
            "seen_at": meta.get("seen_at"),
            "accuracy": None,
        }
        _append(rows_out, record, source)
    return rows_out


def parse_kismet_db(path: Path) -> list[tuple]:
    """Parse a Kismet SQLite log into raw samples (prefer GPS-tagged packets)."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"Cannot open Kismet DB {path}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    source = path.name
    try:
        try:
            names = _tables(conn)
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"Corrupt Kismet DB {path}: {exc}") from exc

        device_index = _load_device_index(conn) if "devices" in names else {}
        rows: list[tuple] = []
        if "packets" in names:
            rows = _parse_from_packets(conn, source, device_index)
        if not rows:
            rows = _parse_from_devices(conn, source, device_index)
        return rows
    finally:
        conn.close()
