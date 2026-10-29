-- Allow real city boundaries (Polygon / MultiPolygon), not only envelopes
ALTER TABLE levels
  ALTER COLUMN bbox TYPE geometry(Geometry, 4326)
  USING bbox::geometry(Geometry, 4326);
