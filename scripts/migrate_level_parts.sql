-- City / city-part metadata for grouped levels (Wuppertal → Elberfeld, …)
ALTER TABLE levels ADD COLUMN IF NOT EXISTS place_kind TEXT NOT NULL DEFAULT 'city';
ALTER TABLE levels ADD COLUMN IF NOT EXISTS geoname_id INTEGER;
ALTER TABLE levels ADD COLUMN IF NOT EXISTS parent_geoname_id INTEGER;
ALTER TABLE levels ADD COLUMN IF NOT EXISTS parent_label TEXT;
ALTER TABLE levels ADD COLUMN IF NOT EXISTS part_label TEXT;
ALTER TABLE levels ADD COLUMN IF NOT EXISTS osm_relation_id BIGINT;
ALTER TABLE levels ADD COLUMN IF NOT EXISTS osm_admin_level INTEGER;

CREATE INDEX IF NOT EXISTS levels_parent_geoname_idx ON levels(user_id, parent_geoname_id);
CREATE INDEX IF NOT EXISTS levels_geoname_idx ON levels(user_id, geoname_id);
