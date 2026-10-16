"""
Fully local forward/reverse geocoding (no Nominatim HTTP).

Data (downloaded at setup — see scripts/prepare_offline_data.py):
  data/cities/cities.sqlite   — GeoNames cities5000
  data/geocode/postal.sqlite    — GeoNames postal codes (allCountries)
"""

from __future__ import annotations

import csv
import io
import math
import re
import sqlite3
import time
import urllib.request
import zipfile
from pathlib import Path

# GeoNames DE postal place_name often names a POI / company, not the city.
_POI_PLACE_RE = re.compile(
    r"(gmbh|mbh|ag\b|kg\b|finanzamt|amtsgericht|klinikum|krankenhaus|"
    r"verwaltung|kreisverwaltung|schule|gymnasium|bahnhof|polizei|"
    r"feuerwehr|sparkasse|volksbank|&\s*co)",
    re.IGNORECASE,
)

ROOT = Path(__file__).resolve().parents[1]
POSTAL_DB = ROOT / "data" / "geocode" / "postal.sqlite"
POSTAL_URL = "https://download.geonames.org/export/zip/allCountries.zip"


def postal_db_available() -> bool:
    return POSTAL_DB.exists() and POSTAL_DB.stat().st_size > 100_000


def _fetch(url: str, timeout: int = 300) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "wardrivrr/1.0 (offline geocode setup)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def build_postal_db(*, force: bool = False) -> Path:
    """Download GeoNames allCountries postal dump → postal.sqlite (worldwide)."""
    if postal_db_available() and not force:
        return POSTAL_DB

    POSTAL_DB.parent.mkdir(parents=True, exist_ok=True)
    print(f"[geocode] downloading postal codes from {POSTAL_URL}")
    raw = _fetch(POSTAL_URL)
    print(f"[geocode] downloaded {len(raw) / 1e6:.1f} MB zip")

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".txt"))
        text = zf.read(name).decode("utf-8", errors="replace")

    # country code, postal code, place name, admin name1, admin code1,
    # admin name2, admin code2, admin name3, admin code3, latitude, longitude, accuracy
    fields = [
        "country_code",
        "postal_code",
        "place_name",
        "admin_name1",
        "admin_code1",
        "admin_name2",
        "admin_code2",
        "admin_name3",
        "admin_code3",
        "latitude",
        "longitude",
        "accuracy",
    ]
    reader = csv.DictReader(io.StringIO(text), fieldnames=fields, delimiter="\t")

    tmp = POSTAL_DB.with_suffix(".sqlite.building")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(str(tmp))
    conn.execute(
        """
        CREATE TABLE postal (
            id INTEGER PRIMARY KEY,
            country_code TEXT,
            postal_code TEXT NOT NULL,
            place_name TEXT,
            admin_name1 TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX postal_code_idx ON postal(postal_code COLLATE NOCASE)"
    )
    conn.execute("CREATE INDEX postal_cc_idx ON postal(country_code)")
    conn.execute(
        """
        CREATE VIRTUAL TABLE postal_rtree USING rtree(
            id, min_lon, max_lon, min_lat, max_lat
        )
        """
    )
    conn.execute(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        [
            ("source", "GeoNames postal allCountries"),
            ("source_url", POSTAL_URL),
            ("license", "CC-BY 4.0"),
            ("built_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        ],
    )

    batch: list[tuple] = []
    rtree_batch: list[tuple] = []
    row_id = 0
    for row in reader:
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (TypeError, ValueError):
            continue
        pc = (row["postal_code"] or "").strip()
        if not pc:
            continue
        row_id += 1
        batch.append(
            (
                row_id,
                (row["country_code"] or "").upper(),
                pc,
                row["place_name"],
                row["admin_name1"],
                lat,
                lon,
            )
        )
        rtree_batch.append((row_id, lon, lon, lat, lat))
        if len(batch) >= 5000:
            conn.executemany(
                """
                INSERT INTO postal (
                    id, country_code, postal_code, place_name, admin_name1,
                    latitude, longitude
                ) VALUES (?,?,?,?,?,?,?)
                """,
                batch,
            )
            conn.executemany(
                "INSERT INTO postal_rtree VALUES (?,?,?,?,?)",
                rtree_batch,
            )
            batch = []
            rtree_batch = []
    if batch:
        conn.executemany(
            """
            INSERT INTO postal (
                id, country_code, postal_code, place_name, admin_name1,
                latitude, longitude
            ) VALUES (?,?,?,?,?,?,?)
            """,
            batch,
        )
        conn.executemany(
            "INSERT INTO postal_rtree VALUES (?,?,?,?,?)",
            rtree_batch,
        )
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM postal").fetchone()[0]
    conn.close()
    if POSTAL_DB.exists():
        POSTAL_DB.unlink()
    tmp.replace(POSTAL_DB)
    print(f"[geocode] wrote {POSTAL_DB} ({n} postal rows)")
    return POSTAL_DB


def ensure_postal_db(*, force: bool = False) -> bool:
    try:
        build_postal_db(force=force)
        return postal_db_available()
    except Exception as exc:
        print(f"[geocode] postal ensure failed: {exc}")
        return False


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


_thread_local = None


def _connect_postal() -> sqlite3.Connection:
    """Per-thread SQLite connection (WAL) — safe for parallel reverse geocode."""
    global _thread_local
    import threading

    if _thread_local is None:
        _thread_local = threading.local()
    if not postal_db_available():
        raise FileNotFoundError(
            f"Postal DB missing at {POSTAL_DB}. Run: python scripts/prepare_offline_data.py"
        )
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(POSTAL_DB), timeout=60, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA query_only=ON")
        _thread_local.conn = conn
    return conn


def nearest_postal(
    lat: float,
    lon: float,
    *,
    pad_deg: float = 0.08,
    city_hint: str | None = None,
) -> dict | None:
    """
    Best GeoNames postal row near a point.

    Prefer rows whose place_name matches city_hint (municipality) and penalize
    POI/company names — raw nearest-centroid often picks the wrong ZIP in DE.
    """
    # Keep the thread-local connection open — do not close() it here.
    conn = _connect_postal()
    hint = (city_hint or "").strip().casefold()
    best = None
    best_score = 1e18
    best_d = 1e18
    for pad in (pad_deg, 0.25, 0.8, 2.0):
        rows = conn.execute(
            """
            SELECT p.postal_code, p.place_name, p.admin_name1, p.country_code,
                   p.latitude, p.longitude
            FROM postal_rtree r
            JOIN postal p ON p.id = r.id
            WHERE r.min_lon BETWEEN ? AND ?
              AND r.min_lat BETWEEN ? AND ?
            """,
            (lon - pad, lon + pad, lat - pad, lat + pad),
        ).fetchall()
        for row in rows:
            d = _haversine_m(lat, lon, float(row["latitude"]), float(row["longitude"]))
            name = (row["place_name"] or "").strip()
            name_l = name.casefold()
            score = d
            if hint:
                if name_l == hint:
                    score -= 5000.0
                elif hint in name_l and len(name_l) <= len(hint) + 20:
                    score -= 800.0
                elif name_l and name_l in hint:
                    score -= 2000.0
            if _POI_PLACE_RE.search(name):
                score += 3500.0
            if score < best_score:
                best_score = score
                best = row
                best_d = d
        if best is not None and best_d < 2000:
            break
    if not best:
        return None
    return {
        "postal_code": best["postal_code"],
        "place_name": best["place_name"],
        "admin_name1": best["admin_name1"],
        "country_code": best["country_code"],
        "lat": float(best["latitude"]),
        "lon": float(best["longitude"]),
        "distance_m": best_d,
    }


def search_postal(
    postalcode: str,
    *,
    country: str | None = None,
    limit: int = 5,
) -> list[dict]:
    pc = (postalcode or "").strip()
    if not pc:
        return []
    conn = _connect_postal()
    if country:
        rows = conn.execute(
            """
            SELECT postal_code, place_name, admin_name1, country_code,
                   latitude, longitude
            FROM postal
            WHERE postal_code = ? COLLATE NOCASE
              AND country_code = ?
            LIMIT ?
            """,
            (pc, country.upper(), limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT postal_code, place_name, admin_name1, country_code,
                   latitude, longitude
            FROM postal
            WHERE postal_code = ? COLLATE NOCASE
            LIMIT ?
            """,
            (pc, limit),
        ).fetchall()
    out = []
    for row in rows:
        lat, lon = float(row["latitude"]), float(row["longitude"])
        pad = 0.05
        out.append(
            {
                "display_name": _format_postal_label(row),
                "lat": lat,
                "lon": lon,
                "bbox": [lon - pad, lat - pad, lon + pad, lat + pad],
                "postal_code": row["postal_code"],
                "place_name": row["place_name"],
                "country_code": row["country_code"],
                "type": "postal_code",
                "class": "place",
            }
        )
    return out


def _format_postal_label(row) -> str:
    parts = [
        row["postal_code"],
        row["place_name"],
        row["admin_name1"],
        row["country_code"],
    ]
    return ", ".join(p for p in parts if p)


def reverse_local(lat: float, lon: float) -> dict | None:
    """
    Point → address (fully local).

    1. Nearest OSM addr:* from a generated level's address pack (street + number)
    2. Municipality name from admin_areas when available
    3. ZIP from GeoNames postal (city-aware), never treat POI names as city
    """
    from cities_db import country_label

    street = housenumber = None
    city = postcode = state = cc = country = None
    source = "local"
    osm_hit = None

    try:
        from address_index import nearest_address

        osm_hit = nearest_address(float(lat), float(lon))
    except Exception:
        osm_hit = None

    if osm_hit:
        street = osm_hit.get("street")
        housenumber = osm_hit.get("housenumber")
        postcode = osm_hit.get("postcode") or None
        city = osm_hit.get("city") or None
        source = "level_osm_addresses"

    try:
        from admin_areas import find_city

        admin = find_city(float(lat), float(lon), city)
    except Exception:
        admin = None
    if admin and admin.get("name"):
        if not city or _POI_PLACE_RE.search(str(city)):
            city = admin["name"]

    postal = None
    if postal_db_available():
        try:
            postal = nearest_postal(lat, lon, city_hint=city)
        except Exception:
            postal = None

    if postal:
        cc = postal.get("country_code")
        state = postal.get("admin_name1")
        if not postcode:
            postcode = postal.get("postal_code")
        if not city or _POI_PLACE_RE.search(str(city)):
            pname = postal.get("place_name")
            if pname and not _POI_PLACE_RE.search(str(pname)):
                city = pname
            elif admin and admin.get("name"):
                city = admin["name"]
        if source == "local":
            source = "local_geonames"

    if not osm_hit and not postal and not city:
        return None

    country = country_label(cc) if cc else None
    if not country and cc:
        country = str(cc).upper()

    # Match OSM-style place labels: "Herbergstraße 8, 58332 Schwelm"
    left = " ".join(p for p in (street, housenumber) if p).strip()
    right = " ".join(p for p in (postcode, city) if p).strip()
    if left and right:
        display = f"{left}, {right}"
    elif left:
        display = left
    elif right:
        display = right
    else:
        display = None

    return {
        "display_name": display,
        "lat": float(lat),
        "lon": float(lon),
        "bbox": None,
        "address": {
            "road": street,
            "house_number": housenumber,
            "postcode": postcode,
            "city": city,
            "town": city,
            "state": state,
            "country": country,
            "country_code": (cc or "").lower() if cc else None,
        },
        "source": source,
        "distance_m": osm_hit.get("distance_m") if osm_hit else None,
    }
