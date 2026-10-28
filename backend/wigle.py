from __future__ import annotations

import csv
import io
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

EMPTY_NAMES = {"", "(no ssid)", "<no ssid>", "[no ssid]", "null", "none"}

_MAC_HEX_RE = re.compile(r"[^0-9a-f]")

TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f%z",
)


def normalize_encryption(auth_mode: str | None) -> str:
    """Map WiGLE AuthMode / Kismet base.crypt strings to a short label."""
    text = (auth_mode or "").upper()
    if "WPA3" in text or "SAE" in text:
        return "WPA3"
    if "WPA2" in text:
        return "WPA2"
    if "WPA" in text:
        return "WPA"
    if "WEP" in text:
        return "WEP"
    stripped = text.strip()
    if not stripped or stripped in {
        "NONE",
        "UNKNOWN",
        "OPEN",
        "[ESS]",
        "ESS",
        "AES-BIP-CMAC256",  # management-frame only, treat as unknown/open-ish
    }:
        return "None"
    if re.fullmatch(r"\[ESS\]", stripped):
        return "None"
    if "ESS" in text and "WPA" not in text and "WEP" not in text:
        return "None"
    return auth_mode.strip() if auth_mode else "Unknown"


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    for fmt in TIME_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _mac_hex(value: str | None) -> str:
    """Normalize a MAC / BSSID to lowercase hex digits only."""
    if not value:
        return ""
    return _MAC_HEX_RE.sub("", str(value).lower())


def is_empty_ssid(name: str | None, network_id: str | None = None) -> bool:
    """True when there is no real SSID/name (placeholder or MAC-as-name)."""
    text = (name or "").strip()
    if not text or text.lower() in EMPTY_NAMES:
        return True
    nid = _mac_hex(network_id)
    if nid and len(nid) >= 12 and _mac_hex(text) == nid:
        # Kismet commonname/base.name often falls back to the BSSID
        return True
    return False


def sanitize_network_name(
    name: str | None, network_id: str | None = None
) -> str | None:
    """Keep real SSIDs; drop empty placeholders and MAC-as-name copies."""
    if is_empty_ssid(name, network_id):
        return None
    return str(name).strip()


def observation_tuple(
    record: dict,
    source_file: str | None = None,
    source_format: str = "wigle",
) -> tuple | None:
    network_id = (record.get("network_id") or "").strip()
    if network_id:
        network_id = network_id.lower().replace("-", ":")
    lat = _to_float(record.get("lat"))
    lon = _to_float(record.get("lon"))
    if not network_id or lat is None or lon is None:
        return None
    if lat == 0.0 and lon == 0.0:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    network_type = (record.get("network_type") or "WIFI").strip().upper()
    name = sanitize_network_name(record.get("name"), network_id)
    seen = record.get("seen_at")
    if isinstance(seen, datetime):
        seen_at = seen if seen.tzinfo else seen.replace(tzinfo=timezone.utc)
    else:
        seen_at = parse_time(str(seen) if seen else None)
    fmt = (source_format or "wigle").strip().lower()
    return (
        name,
        network_id,
        normalize_encryption(record.get("encryption")),
        seen_at,
        _to_float(record.get("signal")),
        _to_float(record.get("accuracy")),
        network_type,
        _to_int(record.get("channel")),
        _to_float(record.get("altitude")),
        lat,
        lon,
        source_file,
        fmt,
    )


def _open_wigle_csv(path: Path) -> io.TextIOBase:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    handle = io.StringIO(text)
    first = handle.readline()
    if not first.lower().startswith("wiglewifi"):
        handle.seek(0)
    return handle


def parse_wigle_csv(path: Path) -> list[tuple]:
    rows: list[tuple] = []
    with _open_wigle_csv(path) as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return rows
        fields = {name.lower(): name for name in reader.fieldnames}

        def col(*names: str) -> str | None:
            for name in names:
                if name.lower() in fields:
                    return fields[name.lower()]
            return None

        mac_col = col("MAC", "network_id", "BSSID")
        ssid_col = col("SSID", "name")
        auth_col = col("AuthMode", "encryption")
        time_col = col("FirstSeen", "time", "seen_at")
        rssi_col = col("RSSI", "signal")
        lat_col = col("CurrentLatitude", "latitude", "lat")
        lon_col = col("CurrentLongitude", "longitude", "lon")
        acc_col = col("AccuracyMeters", "accuracy")
        type_col = col("Type", "network_type")
        ch_col = col("Channel")
        alt_col = col("AltitudeMeters", "altitude")

        source = path.name
        for raw in reader:
            record = {
                "network_id": raw.get(mac_col) if mac_col else None,
                "name": raw.get(ssid_col) if ssid_col else None,
                "encryption": raw.get(auth_col) if auth_col else None,
                "seen_at": raw.get(time_col) if time_col else None,
                "signal": raw.get(rssi_col) if rssi_col else None,
                "lat": raw.get(lat_col) if lat_col else None,
                "lon": raw.get(lon_col) if lon_col else None,
                "accuracy": raw.get(acc_col) if acc_col else None,
                "network_type": raw.get(type_col) if type_col else "WIFI",
                "channel": raw.get(ch_col) if ch_col else None,
                "altitude": raw.get(alt_col) if alt_col else None,
            }
            tup = observation_tuple(record, source, source_format="wigle")
            if tup:
                rows.append(tup)
    return rows


def parse_pwnamap_sqlite(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name, network_id, encryption, time, signal, accuracy,
                   network_type, latitude, longitude
            FROM wigle
            """
        )
        rows: list[tuple] = []
        for raw in cur.fetchall():
            record = {
                "name": raw["name"],
                "network_id": raw["network_id"],
                "encryption": raw["encryption"],
                "seen_at": raw["time"],
                "signal": raw["signal"],
                "accuracy": raw["accuracy"],
                "network_type": raw["network_type"],
                "lat": raw["latitude"],
                "lon": raw["longitude"],
            }
            tup = observation_tuple(record, path.name, source_format="wigle")
            if tup:
                rows.append(tup)
        return rows
    finally:
        conn.close()


def _sqlite_has_table(path: Path, table: str) -> bool:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cur = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def load_path(path: Path) -> list[tuple]:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".txt", ".wiglecsv"}:
        return parse_wigle_csv(path)
    if suffix in {".kismet", ".kis_db"}:
        try:
            from kismet import parse_kismet_db
        except ImportError:
            from backend.kismet import parse_kismet_db

        return parse_kismet_db(path)
    if suffix in {".db", ".sqlite", ".sqlite3"}:
        try:
            from kismet import is_kismet_db, parse_kismet_db
        except ImportError:
            from backend.kismet import is_kismet_db, parse_kismet_db

        if is_kismet_db(path):
            return parse_kismet_db(path)
        if _sqlite_has_table(path, "wigle"):
            return parse_pwnamap_sqlite(path)
        raise ValueError(f"Unrecognized SQLite schema: {path}")
    raise ValueError(f"Unsupported file type: {path}")
