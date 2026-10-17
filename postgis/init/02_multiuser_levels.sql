-- Multi-user, levels, jobs (runs after 01_schema.sql on fresh volumes)

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS api_keys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT 'default',
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS api_keys_user_idx ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS api_keys_prefix_idx ON api_keys(key_prefix);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

-- Ownership on samples / networks (nullable until bootstrap backfill on migrate)
ALTER TABLE signal_samples ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE networks ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS signal_samples_user_idx ON signal_samples(user_id);
CREATE INDEX IF NOT EXISTS networks_user_idx ON networks(user_id);

-- Per-user dedup for samples
DROP INDEX IF EXISTS signal_samples_dedup_idx;
CREATE UNIQUE INDEX signal_samples_dedup_idx
    ON signal_samples (
        COALESCE(user_id, 0),
        network_id,
        COALESCE(seen_at, 'epoch'::timestamptz),
        round(lat::numeric, 6),
        round(lon::numeric, 6),
        round(COALESCE(signal, 0)::numeric, 1),
        COALESCE(source_file, '')
    );

-- Per-user network identity
ALTER TABLE networks DROP CONSTRAINT IF EXISTS networks_pkey;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'networks_user_network_pkey'
    ) THEN
        ALTER TABLE networks ADD CONSTRAINT networks_user_network_pkey PRIMARY KEY (user_id, network_id);
    END IF;
EXCEPTION WHEN others THEN
    -- user_id may still be null on first pass before bootstrap; unique index fallback
    CREATE UNIQUE INDEX IF NOT EXISTS networks_user_network_uidx
        ON networks (COALESCE(user_id, 0), network_id);
END $$;

CREATE TABLE IF NOT EXISTS levels (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    place_query TEXT,
    geofabrik_id TEXT,
    geofabrik_name TEXT,
    pbf_url TEXT,
    profile TEXT NOT NULL CHECK (profile IN ('foot', 'bicycle', 'car', 'big_car', 'small_car')),
    status TEXT NOT NULL DEFAULT 'pending',
    road_km DOUBLE PRECISION DEFAULT 0,
    disk_bytes BIGINT DEFAULT 0,
    networks_count INTEGER DEFAULT 0,
    networks_wifi INTEGER DEFAULT 0,
    networks_bt INTEGER DEFAULT 0,
    networks_ble INTEGER DEFAULT 0,
    explored_km DOUBLE PRECISION DEFAULT 0,
    explored_pct DOUBLE PRECISION DEFAULT 0,
    bbox GEOMETRY(Geometry, 4326),
    place_kind TEXT NOT NULL DEFAULT 'city',
    geoname_id INTEGER,
    parent_geoname_id INTEGER,
    parent_label TEXT,
    part_label TEXT,
    osm_relation_id BIGINT,
    osm_admin_level INTEGER,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS levels_user_idx ON levels(user_id);
CREATE INDEX IF NOT EXISTS levels_parent_geoname_idx ON levels(user_id, parent_geoname_id);
CREATE INDEX IF NOT EXISTS levels_geoname_idx ON levels(user_id, geoname_id);

CREATE TABLE IF NOT EXISTS road_segments (
    id BIGSERIAL PRIMARY KEY,
    level_id INTEGER NOT NULL REFERENCES levels(id) ON DELETE CASCADE,
    osm_id BIGINT,
    highway TEXT,
    name TEXT,
    geom GEOMETRY(LineString, 4326) NOT NULL,
    length_m DOUBLE PRECISION NOT NULL DEFAULT 0,
    is_explored BOOLEAN NOT NULL DEFAULT FALSE,
    explored_at TIMESTAMPTZ,
    last_driven_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS road_segments_level_idx ON road_segments(level_id);
CREATE INDEX IF NOT EXISTS road_segments_geom_gix ON road_segments USING GIST(geom);
CREATE INDEX IF NOT EXISTS road_segments_explored_idx ON road_segments(level_id, is_explored);

CREATE TABLE IF NOT EXISTS jobs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    result JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS jobs_user_status_idx ON jobs(user_id, status);
CREATE INDEX IF NOT EXISTS jobs_queued_idx ON jobs(status, created_at) WHERE status = 'queued';

INSERT INTO app_settings (key, value)
VALUES
    ('bootstrap_complete', 'false'),
    ('default_localize_precision', 'balanced')
ON CONFLICT (key) DO NOTHING;
