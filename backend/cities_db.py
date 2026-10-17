from __future__ import annotations

import csv
import io
import math
import sqlite3
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "cities" / "cities.sqlite"
META_PATH = ROOT / "data" / "cities" / "SOURCE.txt"

# GeoNames cities5000 — worldwide places with pop ≥ 5000 (+ many admin seats). CC-BY 4.0.
GEONAMES_CITIES_URL = "https://download.geonames.org/export/dump/cities5000.zip"
GEONAMES_COUNTRY_URL = "https://download.geonames.org/export/dump/countryInfo.txt"

CITY_CODES = {"PPLC", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPL"}

# Fallback when countryInfo is unavailable
_COUNTRY_FALLBACK = {
    "DE": "Germany",
    "AT": "Austria",
    "CH": "Switzerland",
    "NL": "Netherlands",
    "BE": "Belgium",
    "FR": "France",
    "PL": "Poland",
    "CZ": "Czechia",
    "DK": "Denmark",
    "SE": "Sweden",
    "NO": "Norway",
    "FI": "Finland",
    "IT": "Italy",
    "ES": "Spain",
    "PT": "Portugal",
    "GB": "United Kingdom",
    "IE": "Ireland",
    "US": "United States",
    "CA": "Canada",
    "AU": "Australia",
    "NZ": "New Zealand",
    "JP": "Japan",
    "KR": "South Korea",
    "CN": "China",
    "IN": "India",
    "BR": "Brazil",
    "MX": "Mexico",
    "AR": "Argentina",
    "ZA": "South Africa",
    "TR": "Turkey",
    "RU": "Russia",
    "UA": "Ukraine",
}


def db_available() -> bool:
    return DB_PATH.exists() and DB_PATH.stat().st_size > 100_000


def connect() -> sqlite3.Connection:
    if not db_available():
        raise FileNotFoundError(
            f"Local cities DB missing at {DB_PATH}. "
            "It is downloaded automatically on startup, or run: python scripts/build_cities_db.py"
        )
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _fetch(url: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "wardrivrr/1.0 (offline cities; +https://github.com/)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _load_country_names() -> dict[str, str]:
    names = dict(_COUNTRY_FALLBACK)
    try:
        text = _fetch(GEONAMES_COUNTRY_URL, timeout=60).decode("utf-8", errors="replace")
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            # ISO, ISO3, ISONumeric, fips, Country, Capital, ...
            cc, country = parts[0].strip().upper(), parts[4].strip()
            if len(cc) == 2 and country:
                names[cc] = country
    except Exception:
        pass
    return names


def build_cities_db(
    *,
    min_population: int = 5_000,
    url: str = GEONAMES_CITIES_URL,
    force: bool = False,
) -> Path:
    """
    Download GeoNames cities5000 (worldwide) and build cities.sqlite.
    Safe to call repeatedly; skips if DB exists unless force=True.
    """
    if db_available() and not force:
        return DB_PATH

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"[cities] downloading worldwide cities from {url}")
    raw = _fetch(url)
    print(f"[cities] downloaded {len(raw) / 1e6:.1f} MB zip")

    country_names = _load_country_names()

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".txt"))
        text = zf.read(name).decode("utf-8", errors="replace")

    fields = [
        "geonameid",
        "name",
        "asciiname",
        "alternatenames",
        "latitude",
        "longitude",
        "feature_class",
        "feature_code",
        "country_code",
        "cc2",
        "admin1",
        "admin2",
        "admin3",
        "admin4",
        "population",
        "elevation",
        "dem",
        "timezone",
        "modification_date",
    ]
    reader = csv.DictReader(io.StringIO(text), fieldnames=fields, delimiter="\t")

    tmp = DB_PATH.with_suffix(".sqlite.building")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(str(tmp))
    conn.execute(
        """
        CREATE TABLE cities (
            geoname_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            asciiname TEXT,
            alternatenames TEXT,
            country_code TEXT,
            admin1 TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            population INTEGER NOT NULL DEFAULT 0,
            feature_code TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE countries (
            country_code TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.executemany(
        "INSERT OR REPLACE INTO countries (country_code, name) VALUES (?, ?)",
        list(country_names.items()),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        [
            ("source", "GeoNames cities5000"),
            ("source_url", url),
            ("license", "Creative Commons Attribution 4.0 (CC-BY 4.0)"),
            ("built_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            ("coverage", "worldwide"),
            ("min_population", str(min_population)),
        ],
    )
    conn.execute("CREATE INDEX cities_name_idx ON cities(name COLLATE NOCASE)")
    conn.execute("CREATE INDEX cities_ascii_idx ON cities(asciiname COLLATE NOCASE)")
    conn.execute("CREATE INDEX cities_pop_idx ON cities(population DESC)")
    conn.execute("CREATE INDEX cities_cc_idx ON cities(country_code)")

    batch: list[tuple] = []
    kept = 0

    def flush() -> None:
        nonlocal batch, kept
        if not batch:
            return
        conn.executemany(
            """
            INSERT OR REPLACE INTO cities (
                geoname_id, name, asciiname, alternatenames, country_code,
                admin1, latitude, longitude, population, feature_code
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            batch,
        )
        kept += len(batch)
        batch = []

    for row in reader:
        if row["feature_class"] != "P":
            continue
        fcode = row["feature_code"] or ""
        if fcode not in CITY_CODES:
            continue
        try:
            pop = int(row["population"] or 0)
        except ValueError:
            pop = 0
        # Keep all admin seats; filter plain PPL by population
        if fcode == "PPL" and pop < min_population:
            continue
        if pop < 1_000 and fcode not in {"PPLC", "PPLA", "PPLA2"}:
            continue
        batch.append(
            (
                int(row["geonameid"]),
                row["name"],
                row["asciiname"],
                (row["alternatenames"] or "")[:4000],
                row["country_code"],
                row["admin1"],
                float(row["latitude"]),
                float(row["longitude"]),
                pop,
                fcode,
            )
        )
        if len(batch) >= 2000:
            flush()
    flush()
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
    conn.close()

    if DB_PATH.exists():
        DB_PATH.unlink()
    tmp.replace(DB_PATH)

    META_PATH.write_text(
        "\n".join(
            [
                "Offline cities database for wardrivrr levels place search.",
                f"Source: GeoNames cities5000 ({url})",
                "License: CC-BY 4.0 — https://creativecommons.org/licenses/by/4.0/",
                "Country names: GeoNames countryInfo.txt",
                f"Built: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
                f"Cities: {n}",
                "Coverage: worldwide",
                "See thanks.md for attribution and how city → map-pack resolution works.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"[cities] wrote {DB_PATH} ({n} cities worldwide)")
    return DB_PATH


def ensure_cities_db(*, force: bool = False) -> bool:
    """Ensure the worldwide cities DB exists (download + build on first use)."""
    try:
        build_cities_db(force=force)
        return db_available()
    except Exception as exc:
        print(f"[cities] ensure failed: {exc}")
        return False


_country_cache: dict[str, str] | None = None


def country_label(cc: str | None) -> str:
    global _country_cache
    if not cc:
        return ""
    code = cc.upper()
    if _country_cache is None:
        _country_cache = dict(_COUNTRY_FALLBACK)
        if db_available():
            try:
                conn = connect()
                try:
                    rows = conn.execute("SELECT country_code, name FROM countries").fetchall()
                    for row in rows:
                        _country_cache[row["country_code"].upper()] = row["name"]
                finally:
                    conn.close()
            except Exception:
                pass
    return _country_cache.get(code, code)


def estimate_radius_deg(population: int | None, feature_code: str | None = None) -> float:
    """Rough urban half-span in degrees from population (local, no network)."""
    pop = max(int(population or 0), 5_000)
    km = 0.4 * math.sqrt(pop / 1000.0)
    if feature_code == "PPLC":
        km *= 1.35
    elif feature_code in {"PPLA", "PPLA2"}:
        km *= 1.15
    km = max(4.0, min(km, 45.0))
    return km / 111.32


def bbox_from_point(lat: float, lon: float, radius_deg: float) -> list[float]:
    lat_pad = radius_deg
    lon_pad = radius_deg / max(0.2, math.cos(math.radians(lat)))
    return [lon - lon_pad, lat - lat_pad, lon + lon_pad, lat + lat_pad]


def approximate_boundary(lat: float, lon: float, radius_deg: float, sides: int = 48) -> dict:
    """Closed ring polygon approximating the city extent (preview until PBF clip)."""
    lat_pad = radius_deg
    lon_pad = radius_deg / max(0.2, math.cos(math.radians(lat)))
    ring = []
    for i in range(sides):
        ang = 2 * math.pi * i / sides
        ring.append([lon + lon_pad * math.cos(ang), lat + lat_pad * math.sin(ang)])
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def search_cities(query: str, limit: int = 10, min_population: int = 5_000) -> list[dict]:
    """
    Local search over the worldwide GeoNames-derived cities table.
    No external HTTP after the DB is built.
    """
    q = (query or "").strip()
    if not q:
        return []
    tokens = [t for t in q.replace(",", " ").split() if t]
    if not tokens:
        return []

    conn = connect()
    try:
        like = f"%{tokens[0]}%"
        exact = tokens[0]
        rows = conn.execute(
            """
            SELECT geoname_id, name, asciiname, country_code, admin1,
                   latitude, longitude, population, feature_code
            FROM cities
            WHERE population >= ?
              AND (
                name LIKE ? COLLATE NOCASE
                OR asciiname LIKE ? COLLATE NOCASE
                OR alternatenames LIKE ? COLLATE NOCASE
              )
            ORDER BY
              CASE
                WHEN name = ? COLLATE NOCASE OR asciiname = ? COLLATE NOCASE THEN 0
                WHEN name LIKE ? COLLATE NOCASE OR asciiname LIKE ? COLLATE NOCASE THEN 1
                ELSE 2
              END,
              population DESC
            LIMIT ?
            """,
            (
                min_population,
                like,
                like,
                f"%{exact}%",
                exact,
                exact,
                f"{exact}%",
                f"{exact}%",
                max(limit * 3, 20),
            ),
        ).fetchall()
    finally:
        conn.close()

    extra = [t.lower() for t in tokens[1:]]
    out = []
    seen = set()
    for row in rows:
        cc = (row["country_code"] or "").upper()
        cname = country_label(cc).lower()
        if extra:
            if not any(t == cc.lower() or t in cname for t in extra):
                # still allow if extra tokens are part of the city name only
                name_l = (row["name"] or "").lower()
                if not all(t in name_l or t == cc.lower() or t in cname for t in extra):
                    continue
        key = (row["name"], cc)
        if key in seen:
            continue
        seen.add(key)
        lat = float(row["latitude"])
        lon = float(row["longitude"])
        pop = int(row["population"] or 0)
        fcode = row["feature_code"]
        radius = estimate_radius_deg(pop, fcode)
        bbox = bbox_from_point(lat, lon, radius)
        label = f"{row['name']}, {country_label(cc)}" if cc else row["name"]
        out.append(
            {
                "geoname_id": row["geoname_id"],
                "name": row["name"],
                "label": label,
                "display_name": label,
                "country_code": cc,
                "country": country_label(cc),
                "admin1": row["admin1"],
                "lat": lat,
                "lon": lon,
                "population": pop,
                "feature_code": fcode,
                "bbox": bbox,
                "boundary": approximate_boundary(lat, lon, radius),
                "boundary_approximate": True,
                "place_type": "city",
                "place_query": label,
            }
        )
        if len(out) >= limit:
            break
    return out


def lookup_city_by_label(label: str) -> dict | None:
    """Resolve a stored place_query / label back to local city row."""
    hits = search_cities(label, limit=5, min_population=1_000)
    if not hits:
        return None
    for h in hits:
        if h["label"].lower() == label.strip().lower():
            return h
    return hits[0]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def nearest_city(
    lat: float,
    lon: float,
    *,
    max_km: float = 25.0,
    min_population: int = 5_000,
) -> dict | None:
    """Closest GeoNames city within max_km (for Drive suggest when admin_areas is empty)."""
    # ~1 deg lat ≈ 111 km; pad bbox then rank by haversine
    pad = max(0.05, (max_km / 111.0) * 1.25)
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT geoname_id, name, asciiname, country_code, admin1,
                   latitude, longitude, population, feature_code
            FROM cities
            WHERE population >= ?
              AND latitude BETWEEN ? AND ?
              AND longitude BETWEEN ? AND ?
            """,
            (min_population, lat - pad, lat + pad, lon - pad, lon + pad),
        ).fetchall()
    finally:
        conn.close()
    best = None
    best_d = None
    for row in rows:
        d = _haversine_km(lat, lon, float(row["latitude"]), float(row["longitude"]))
        if d > max_km:
            continue
        if best_d is None or d < best_d:
            best_d = d
            best = row
    if not best:
        return None
    clat = float(best["latitude"])
    clon = float(best["longitude"])
    pop = int(best["population"] or 0)
    fcode = best["feature_code"]
    radius = estimate_radius_deg(pop, fcode)
    cc = (best["country_code"] or "").upper()
    label = f"{best['name']}, {country_label(cc)}" if cc else best["name"]
    return {
        "geoname_id": int(best["geoname_id"]),
        "name": best["name"],
        "label": label,
        "country_code": cc,
        "lat": clat,
        "lon": clon,
        "population": pop,
        "feature_code": fcode,
        "bbox": bbox_from_point(clat, clon, radius),
        "boundary": approximate_boundary(clat, clon, radius),
        "boundary_approximate": True,
        "distance_km": best_d,
        "place_type": "city",
        "place_query": label,
    }
