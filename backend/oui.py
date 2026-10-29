"""
MAC / OUI vendor lookup from the public IEEE registries.

Downloads (on first use / startup) — CSV form has full MA-L / MA-M / MA-S assignments:
  https://standards-oui.ieee.org/oui/oui.csv
  https://standards-oui.ieee.org/oui28/mam.csv
  https://standards-oui.ieee.org/oui36/oui36.csv

Stored locally as data/oui/oui.sqlite for offline prefix lookup.
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "oui" / "oui.sqlite"
META_PATH = ROOT / "data" / "oui" / "SOURCE.txt"

IEEE_CSV_SOURCES = (
    ("https://standards-oui.ieee.org/oui/oui.csv", 24),
    ("https://standards-oui.ieee.org/oui28/mam.csv", 28),
    ("https://standards-oui.ieee.org/oui36/oui36.csv", 36),
)

_HEX_RE = re.compile(r"[^0-9A-Fa-f]")

_lookup_conn: sqlite3.Connection | None = None
_lookup_lock = threading.Lock()
_backfill_started = False


def db_available() -> bool:
    return DB_PATH.exists() and DB_PATH.stat().st_size > 50_000


def normalize_mac_hex(value: str | None) -> str:
    if not value:
        return ""
    return _HEX_RE.sub("", str(value)).upper()


def format_oui(hex_prefix: str) -> str:
    """AA:BB:CC (or longer) for UI labels."""
    h = normalize_mac_hex(hex_prefix)
    if len(h) < 2:
        return h
    return ":".join(h[i : i + 2] for i in range(0, len(h), 2))


def _fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "wardrivrr/1.0 (IEEE OUI; +https://github.com/)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_ieee_csv(text: str, default_bits: int) -> list[tuple[str, int, str]]:
    """Parse IEEE RA CSV → (prefix_hex, bits, vendor)."""
    rows: list[tuple[str, int, str]] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        assignment = (row.get("Assignment") or "").strip()
        vendor = (row.get("Organization Name") or "").strip()
        if not assignment or not vendor:
            continue
        if vendor.upper() in {"PRIVATE", "N/A", "NA"}:
            continue
        hex_prefix = normalize_mac_hex(assignment)
        if len(hex_prefix) < 6:
            continue
        bits = len(hex_prefix) * 4
        if bits not in {24, 28, 36}:
            bits = default_bits
            need = bits // 4
            if len(hex_prefix) < need:
                continue
            hex_prefix = hex_prefix[:need]
        rows.append((hex_prefix, bits, vendor))
    return rows


def build_oui_db(*, force: bool = False) -> Path:
    """Download IEEE OUI CSV registries and build the local SQLite cache."""
    if db_available() and not force:
        return DB_PATH

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    building = DB_PATH.with_suffix(".sqlite.building")
    if building.exists():
        building.unlink()

    all_rows: list[tuple[str, int, str]] = []
    sources_ok: list[str] = []
    for url, bits in IEEE_CSV_SOURCES:
        print(f"[oui] downloading {url}", flush=True)
        raw = _fetch(url)
        # IEEE files are Latin-1-ish; utf-8 with replace is fine for names
        text = raw.decode("utf-8", errors="replace")
        parsed = _parse_ieee_csv(text, bits)
        print(f"[oui]   {len(parsed)} assignments ({bits}-bit)", flush=True)
        all_rows.extend(parsed)
        sources_ok.append(url)

    if not all_rows:
        raise RuntimeError("IEEE OUI download returned no assignments")

    # Longer / later assignments win on duplicate prefix keys
    by_prefix: dict[str, tuple[int, str]] = {}
    for prefix, bits, vendor in all_rows:
        by_prefix[prefix] = (bits, vendor)

    conn = sqlite3.connect(str(building))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE oui (
                prefix TEXT PRIMARY KEY,
                bits INTEGER NOT NULL,
                vendor TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX oui_bits_idx ON oui (bits)")
        conn.execute("CREATE INDEX oui_vendor_idx ON oui (vendor)")
        conn.executemany(
            "INSERT INTO oui (prefix, bits, vendor) VALUES (?, ?, ?)",
            [(p, b, v) for p, (b, v) in by_prefix.items()],
        )
        conn.execute(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?), (?, ?), (?, ?)",
            (
                "built_at",
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "count",
                str(len(by_prefix)),
                "source",
                "IEEE standards-oui CSV",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    if DB_PATH.exists():
        DB_PATH.unlink()
    building.replace(DB_PATH)

    META_PATH.write_text(
        "\n".join(
            [
                "IEEE Registration Authority — OUI / MA-L, MA-M, MA-S (CSV)",
                "https://standards-oui.ieee.org/",
                *sources_ok,
                f"Built: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
                f"Assignments: {len(by_prefix)}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"[oui] wrote {DB_PATH} ({len(by_prefix)} prefixes)", flush=True)
    _reset_lookup_conn()
    return DB_PATH


def ensure_oui_db(*, force: bool = False) -> bool:
    try:
        build_oui_db(force=force)
        return db_available()
    except Exception as exc:
        print(f"[oui] ensure failed: {exc}", flush=True)
        return False


def _reset_lookup_conn() -> None:
    global _lookup_conn
    with _lookup_lock:
        if _lookup_conn is not None:
            try:
                _lookup_conn.close()
            except Exception:
                pass
            _lookup_conn = None


def _conn() -> sqlite3.Connection | None:
    global _lookup_conn
    if not db_available():
        return None
    with _lookup_lock:
        if _lookup_conn is None:
            _lookup_conn = sqlite3.connect(
                f"file:{DB_PATH.as_posix()}?mode=ro",
                uri=True,
                check_same_thread=False,
            )
            _lookup_conn.row_factory = sqlite3.Row
        return _lookup_conn


def lookup_vendor(mac: str | None) -> str | None:
    """Return organization name for a MAC/BSSID, or None if unknown."""
    hex_mac = normalize_mac_hex(mac)
    if len(hex_mac) < 6:
        return None
    conn = _conn()
    if conn is None:
        return None
    # Prefer most-specific assignment (MA-S 36 → MA-M 28 → MA-L 24).
    for bits in (36, 28, 24):
        n = bits // 4
        if len(hex_mac) < n:
            continue
        prefix = hex_mac[:n]
        try:
            row = conn.execute(
                "SELECT vendor FROM oui WHERE prefix = ?", (prefix,)
            ).fetchone()
        except sqlite3.Error:
            return None
        if row and row["vendor"]:
            return str(row["vendor"]).strip() or None
    return None


def prefixes_for_vendor(vendor: str, *, limit: int = 200) -> list[str]:
    """Hex prefixes (no colons) registered to this exact Organization Name."""
    name = (vendor or "").strip()
    if not name:
        return []
    conn = _conn()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT prefix FROM oui
            WHERE vendor = ?
            ORDER BY bits ASC, prefix ASC
            LIMIT ?
            """,
            (name, limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [str(r["prefix"]) for r in rows if r["prefix"]]


def ensure_vendor_column(conn=None) -> None:
    """Add networks.vendor if missing (existing installs skip init SQL)."""
    from db import connect as db_connect

    own = conn is None
    if own:
        conn = db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'networks'
                  AND column_name = 'vendor'
                """
            )
            if cur.fetchone():
                return
            cur.execute("ALTER TABLE networks ADD COLUMN vendor TEXT")
        conn.commit()
        print("[oui] added networks.vendor column", flush=True)
    finally:
        if own:
            conn.close()


def backfill_network_vendors(*, batch: int = 2000) -> int:
    """Fill NULL vendor on existing networks. Returns rows updated with a name."""
    if not db_available():
        return 0
    from db import connect_dict

    ensure_vendor_column()
    updated = 0
    conn = connect_dict()
    try:
        while True:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT network_id, user_id
                    FROM networks
                    WHERE vendor IS NULL
                    LIMIT %s
                    """,
                    (batch,),
                )
                rows = cur.fetchall()
                if not rows:
                    break
                for row in rows:
                    vendor = lookup_vendor(row["network_id"])
                    # '' = looked up, unknown — avoids re-scanning forever
                    cur.execute(
                        """
                        UPDATE networks
                        SET vendor = %s
                        WHERE user_id = %s AND network_id = %s
                          AND vendor IS NULL
                        """,
                        (vendor or "", row["user_id"], row["network_id"]),
                    )
                    if vendor:
                        updated += 1
            conn.commit()
            if len(rows) < batch:
                break
    finally:
        conn.close()
    if updated:
        print(f"[oui] backfilled vendor on {updated} networks", flush=True)
    return updated


def list_vendors_for_user(user_id: int, *, max_ouis: int = 8) -> list[dict]:
    """
    Vendors present in this user's triangulated networks.

    Each entry: {vendor, count, ouis: ["AA:BB:CC", ...], label: "Apple, Inc. (AA:BB:CC, …)"}
    """
    from db import connect_dict

    ensure_vendor_column()
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT network_id, vendor
                FROM networks
                WHERE user_id = %s
                  AND network_id IS NOT NULL
                  AND length(translate(upper(network_id), ':.- ', '')) >= 6
                """,
                (user_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    # vendor -> {count, prefixes set}
    buckets: dict[str, dict] = {}
    for row in rows:
        mac = normalize_mac_hex(row.get("network_id"))
        if len(mac) < 6:
            continue
        vendor = (row.get("vendor") or "").strip() or None
        if not vendor:
            vendor = lookup_vendor(mac)
        if not vendor:
            continue
        bucket = buckets.setdefault(vendor, {"count": 0, "prefixes": set()})
        bucket["count"] += 1
        # Prefer 24-bit OUI for the label chip list
        bucket["prefixes"].add(mac[:6])

    out: list[dict] = []
    for vendor, info in buckets.items():
        ouis_hex = sorted(info["prefixes"])
        ouis = [format_oui(p) for p in ouis_hex[:max_ouis]]
        more = len(ouis_hex) - len(ouis)
        oui_part = ", ".join(ouis)
        if more > 0:
            oui_part = f"{oui_part}, +{more}" if oui_part else f"+{more}"
        label = f"{vendor} ({oui_part})" if oui_part else vendor
        out.append(
            {
                "vendor": vendor,
                "count": info["count"],
                "ouis": ouis,
                "oui_count": len(ouis_hex),
                "label": label,
            }
        )
    out.sort(key=lambda x: (-int(x["count"]), x["vendor"].lower()))
    return out


def vendor_match_clause(vendor: str) -> tuple[str, list]:
    """
    SQL fragment + params matching networks of this IEEE organization.

    Uses stored vendor column and/or MAC prefix list from the OUI DB so
    filtering works before backfill finishes.
    """
    name = (vendor or "").strip()
    if not name:
        return "TRUE", []
    prefixes = prefixes_for_vendor(name, limit=400)
    mac_expr = "translate(upper(network_id), ':.- ', '')"
    parts = ["vendor = %s"]
    params: list = [name]
    if prefixes:
        # Group by length for prefix equality via left()
        by_len: dict[int, list[str]] = {}
        for p in prefixes:
            by_len.setdefault(len(p), []).append(p)
        for length, plist in by_len.items():
            parts.append(f"left({mac_expr}, %s) = ANY(%s)")
            params.extend([length, plist])
    return "(" + " OR ".join(parts) + ")", params


def start_oui_background() -> None:
    """Download OUI DB (if needed), ensure column, backfill — non-blocking."""
    global _backfill_started
    if _backfill_started:
        return
    _backfill_started = True

    def _run():
        try:
            ensure_oui_db()
            ensure_vendor_column()
            backfill_network_vendors()
        except Exception as exc:
            print(f"[oui] background: {exc}", flush=True)

    threading.Thread(target=_run, name="oui-init", daemon=True).start()
