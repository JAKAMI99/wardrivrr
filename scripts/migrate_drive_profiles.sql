-- Drive profiles (big_car / small_car / bicycle / foot) + last_driven_at on segments.
-- Existing profile='car' stays valid (app aliases it to small_car).

ALTER TABLE road_segments
  ADD COLUMN IF NOT EXISTS last_driven_at TIMESTAMPTZ;

-- Backfill last driven from first unlock when present
UPDATE road_segments
SET last_driven_at = explored_at
WHERE last_driven_at IS NULL AND explored_at IS NOT NULL;

ALTER TABLE levels DROP CONSTRAINT IF EXISTS levels_profile_check;
ALTER TABLE levels
  ADD CONSTRAINT levels_profile_check
  CHECK (profile IN ('foot', 'bicycle', 'car', 'big_car', 'small_car'));
