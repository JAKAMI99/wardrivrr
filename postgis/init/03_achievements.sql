-- Drive distance + achievements (safe to re-run)

CREATE TABLE IF NOT EXISTS drive_day_km (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day DATE NOT NULL,
    km_total DOUBLE PRECISION NOT NULL DEFAULT 0,
    km_night DOUBLE PRECISION NOT NULL DEFAULT 0,
    km_explored DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS user_achievements (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    achievement_id TEXT NOT NULL,
    tier INTEGER NOT NULL DEFAULT 1,
    unlocked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    meta JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (user_id, achievement_id, tier)
);

CREATE INDEX IF NOT EXISTS user_achievements_user_idx ON user_achievements(user_id);
