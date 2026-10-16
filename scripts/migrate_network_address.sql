-- Address + location confidence on triangulated networks
ALTER TABLE networks ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE networks ADD COLUMN IF NOT EXISTS city TEXT;
ALTER TABLE networks ADD COLUMN IF NOT EXISTS postcode TEXT;
ALTER TABLE networks ADD COLUMN IF NOT EXISTS country TEXT;
ALTER TABLE networks ADD COLUMN IF NOT EXISTS country_code TEXT;
ALTER TABLE networks ADD COLUMN IF NOT EXISTS location_accuracy_m REAL;
ALTER TABLE networks ADD COLUMN IF NOT EXISTS avg_gps_accuracy_m REAL;

CREATE INDEX IF NOT EXISTS networks_postcode_idx ON networks (postcode);
CREATE INDEX IF NOT EXISTS networks_city_idx ON networks (lower(city));
CREATE INDEX IF NOT EXISTS networks_address_idx ON networks (lower(address));
