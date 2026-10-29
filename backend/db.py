import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor, execute_values

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def db_kwargs() -> dict:
    # Prefer 127.0.0.1 over "localhost" — on Windows, localhost can hit IPv6
    # first and stall ~2s per new Postgres connection.
    host = os.getenv("DB_HOST", "127.0.0.1") or "127.0.0.1"
    if host.strip().lower() == "localhost":
        host = "127.0.0.1"
    return {
        "host": host,
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", "wardriving"),
        "user": os.getenv("DB_USER", "explorer"),
        "password": os.getenv("DB_PASS", "secure_password_here"),
    }


def connect(**overrides):
    cfg = db_kwargs()
    cfg.update(overrides)
    return psycopg2.connect(**cfg)


def connect_dict(**overrides):
    conn = connect(**overrides)
    conn.cursor_factory = RealDictCursor
    return conn


# Hot-path indexes added after the init SQL shipped; existing installs never
# re-run postgis/init, so they are created at API startup.
RUNTIME_INDEXES = (
    # Fog unlock "ahead" lookup (same OSM way within a level)
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS road_segments_level_osm_idx "
    "ON road_segments (level_id, osm_id)",
    # Per-network strongest-sample window in localize._fetch_samples
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS signal_samples_user_net_sig_idx "
    "ON signal_samples (user_id, network_id, signal DESC NULLS LAST)",
    # Drive session stats / anomalies (user + time window)
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS signal_samples_user_seen_idx "
    "ON signal_samples (user_id, seen_at)",
    # Below-sea / mountain achievement counts
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS signal_samples_below_sea_idx "
    "ON signal_samples (user_id) WHERE altitude < 0",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS signal_samples_mountain_idx "
    "ON signal_samples (user_id) WHERE altitude > 700",
)


# Idempotent schema fixes for DBs created before drive-profile rename.
_RUNTIME_SCHEMA_SQL = (
    """
    ALTER TABLE road_segments
      ADD COLUMN IF NOT EXISTS last_driven_at TIMESTAMPTZ
    """,
    """
    ALTER TABLE levels DROP CONSTRAINT IF EXISTS levels_profile_check
    """,
    """
    ALTER TABLE levels
      ADD CONSTRAINT levels_profile_check
      CHECK (profile IN ('foot', 'bicycle', 'car', 'big_car', 'small_car'))
    """,
)


def ensure_runtime_indexes() -> None:
    conn = connect()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            for sql in _RUNTIME_SCHEMA_SQL:
                try:
                    cur.execute(sql)
                except psycopg2.Error as exc:
                    print(f"[db] schema skipped: {exc}".strip(), flush=True)
            for sql in RUNTIME_INDEXES:
                try:
                    cur.execute(sql)
                except psycopg2.Error as exc:
                    print(f"[db] index skipped: {exc}".strip(), flush=True)
    finally:
        conn.close()


INSERT_SQL = """
INSERT INTO signal_samples (
    name, network_id, encryption, seen_at, signal, accuracy,
    network_type, channel, altitude, lat, lon, source_file, source_format, user_id
) VALUES %s
ON CONFLICT DO NOTHING
"""


def insert_observations(rows: list[tuple], conn=None, user_id: int | None = None) -> int:
    """Insert raw signal samples.

    Row shapes:
      13 fields — parser output (no user_id): name…source_format
      14 fields — already includes user_id
    """
    if not rows:
        return 0
    prepared = []
    for row in rows:
        n = len(row)
        if n == 14:
            prepared.append(tuple(row))
        elif n == 13:
            prepared.append(tuple(row) + (user_id,))
        elif n == 12:
            # Legacy without source_format
            prepared.append(tuple(row) + ("unknown", user_id))
        else:
            raise ValueError(f"signal sample row has {n} fields, expected 12–14")
    own = conn is None
    if own:
        conn = connect()
    try:
        with conn.cursor() as cur:
            execute_values(cur, INSERT_SQL, prepared, page_size=1000)
        conn.commit()
        return len(prepared)
    finally:
        if own:
            conn.close()


def get_setting(key: str, default: str | None = None, conn=None) -> str | None:
    own = conn is None
    if own:
        conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM app_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            if not row:
                return default
            if isinstance(row, dict):
                return row.get("value", default)
            return row[0]
    finally:
        if own:
            conn.close()


def set_setting(key: str, value: str, conn=None) -> None:
    own = conn is None
    if own:
        conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (key, value),
            )
        conn.commit()
    finally:
        if own:
            conn.close()


def get_user_setting(user_id: int, key: str, default: str | None = None, conn=None) -> str | None:
    own = conn is None
    if own:
        conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM user_settings WHERE user_id = %s AND key = %s",
                (user_id, key),
            )
            row = cur.fetchone()
            if not row:
                return default
            return row[0] if not isinstance(row, dict) else row.get("value", default)
    finally:
        if own:
            conn.close()


def set_user_setting(user_id: int, key: str, value: str, conn=None) -> None:
    own = conn is None
    if own:
        conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_settings (user_id, key, value) VALUES (%s, %s, %s)
                ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value
                """,
                (user_id, key, value),
            )
        conn.commit()
    finally:
        if own:
            conn.close()
