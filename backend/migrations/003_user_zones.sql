-- Areas drawn by operators on the map (phase 16). The polygon is stored as
-- JSON [[lat, lon], ...], the same order as config/zones.toml: the backend
-- only reads it back whole, it never queries inside it.
CREATE TABLE user_zones (
    name text PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('restricted', 'watch')),
    polygon jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
