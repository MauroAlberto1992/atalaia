-- Durable history of every accepted position (phase 12).
-- Requires the TimescaleDB and PostGIS extensions (timescaledb-ha image).

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE ships (
    mmsi       integer PRIMARY KEY,
    name       text        NOT NULL DEFAULT '',
    first_seen timestamptz NOT NULL,
    last_seen  timestamptz NOT NULL
);

-- One row per accepted position. lat/lon are stored as written by the
-- recorder (COPY can't call PostGIS functions); geom is derived from them so
-- spatial queries (routes, "who crossed this area") can use PostGIS directly.
CREATE TABLE positions (
    time         timestamptz NOT NULL,
    mmsi         integer     NOT NULL,
    lat          double precision NOT NULL,
    lon          double precision NOT NULL,
    geom         geography(Point, 4326)
                 GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography) STORED,
    sog          real     NOT NULL,
    cog          real     NOT NULL,
    true_heading smallint NOT NULL,
    nav_status   smallint NOT NULL
);

-- Hypertable: rows are split into 1-day chunks by time, so recent data stays
-- small and old chunks can be compressed or dropped as a whole.
SELECT create_hypertable('positions', by_range('time', INTERVAL '1 day'));

-- "Route of ship X between t1 and t2" is the main query (phase 13).
CREATE INDEX positions_mmsi_time ON positions (mmsi, time DESC);

-- Compress chunks older than a day, grouped by ship (one ship's points
-- compress well together and are read together).
ALTER TABLE positions SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'mmsi',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('positions', INTERVAL '1 day');
-- Retention is set by the application at startup (configurable), see db.py.
