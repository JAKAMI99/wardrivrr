CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS signal_samples (
    id BIGSERIAL PRIMARY KEY,
    name TEXT,
    network_id TEXT NOT NULL,
    encryption TEXT,
    seen_at TIMESTAMPTZ,
    signal REAL,
    accuracy REAL,
    network_type TEXT NOT NULL,
    channel INTEGER,
    altitude REAL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    geom GEOMETRY(Point, 4326)
        GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon, lat), 4326)) STORED,
    source_file TEXT,
    source_format TEXT NOT NULL DEFAULT 'wigle',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT signal_samples_lat_range CHECK (lat BETWEEN -90 AND 90),
    CONSTRAINT signal_samples_lon_range CHECK (lon BETWEEN -180 AND 180)
);

CREATE UNIQUE INDEX IF NOT EXISTS signal_samples_dedup_idx
    ON signal_samples (
        network_id,
        COALESCE(seen_at, 'epoch'::timestamptz),
        round(lat::numeric, 6),
        round(lon::numeric, 6),
        round(COALESCE(signal, 0)::numeric, 1),
        COALESCE(source_file, '')
    );

CREATE INDEX IF NOT EXISTS signal_samples_geom_gix ON signal_samples USING GIST (geom);
CREATE INDEX IF NOT EXISTS signal_samples_seen_at_idx ON signal_samples (seen_at);
CREATE INDEX IF NOT EXISTS signal_samples_type_idx ON signal_samples (network_type);
CREATE INDEX IF NOT EXISTS signal_samples_encryption_idx ON signal_samples (encryption);
CREATE INDEX IF NOT EXISTS signal_samples_network_id_idx ON signal_samples (network_id);
CREATE INDEX IF NOT EXISTS signal_samples_name_idx ON signal_samples (lower(name));

CREATE TABLE IF NOT EXISTS networks (
    network_id TEXT PRIMARY KEY,
    name TEXT,
    encryption TEXT,
    network_type TEXT NOT NULL,
    channel INTEGER,
    sample_count INTEGER NOT NULL DEFAULT 0,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    altitude REAL,
    avg_signal REAL,
    first_seen TIMESTAMPTZ,
    last_seen TIMESTAMPTZ,
    localization_mode TEXT NOT NULL DEFAULT '2d',
    address TEXT,
    city TEXT,
    postcode TEXT,
    country TEXT,
    country_code TEXT,
    location_accuracy_m REAL,
    avg_gps_accuracy_m REAL,
    vendor TEXT,
    geom GEOMETRY(Point, 4326)
        GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon, lat), 4326)) STORED,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT networks_lat_range CHECK (lat BETWEEN -90 AND 90),
    CONSTRAINT networks_lon_range CHECK (lon BETWEEN -180 AND 180)
);

CREATE INDEX IF NOT EXISTS networks_geom_gix ON networks USING GIST (geom);
CREATE INDEX IF NOT EXISTS networks_type_idx ON networks (network_type);
CREATE INDEX IF NOT EXISTS networks_encryption_idx ON networks (encryption);
CREATE INDEX IF NOT EXISTS networks_name_idx ON networks (lower(name));
CREATE INDEX IF NOT EXISTS networks_last_seen_idx ON networks (last_seen);
CREATE INDEX IF NOT EXISTS networks_postcode_idx ON networks (postcode);
CREATE INDEX IF NOT EXISTS networks_city_idx ON networks (lower(city));
CREATE INDEX IF NOT EXISTS networks_address_idx ON networks (lower(address));

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO app_settings (key, value)
VALUES ('default_localization_mode', '2d')
ON CONFLICT (key) DO NOTHING;

-- Legacy alias for older tooling that still references observations
CREATE OR REPLACE VIEW observations AS
SELECT
    id,
    name,
    network_id,
    encryption,
    seen_at,
    signal,
    accuracy,
    network_type,
    channel,
    altitude,
    lat,
    lon,
    geom,
    source_file,
    ingested_at
FROM signal_samples;
