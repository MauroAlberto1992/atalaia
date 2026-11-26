# Phase 12 spec — Record every position in a database

Status: approved.

(Phase 11, the real port list, is in progress on its own branch, waiting for OpenStreetMap access.)

## Goal
Keep the history of every ship durably, so that later phases can show past
routes (phase 13) and work with user-drawn areas (phase 14). Today, history
lives only in memory and is lost on restart.

## Why PostgreSQL + TimescaleDB + PostGIS (not Redis)
- **Redis** is an in-memory cache and message bus. The live state already lives in memory (`TrackStore`); what is missing is durable, queryable history.
- **TimescaleDB** handles a constant stream of time-stamped rows: data is split by time, older data is compressed and expired automatically.
- **PostGIS** gives the geographic queries the next phases need: routes as lines, and "which ships crossed this area?".
- **Expected volume:** with about 100 ships reporting every 2–10 s, a few tens of rows per second, i.e. 2–3 million rows per day.

## Scope
1. **Database in Docker Compose**
   - Image: TimescaleDB with PostGIS, an exact pinned tag.
   - Data on a named volume, so it survives restarts.
   - Healthcheck; the backend waits for the database to be healthy.
   - The database password lives in `.env` (`POSTGRES_PASSWORD`, added to `.env.example`), never in the repository.
2. **Schema, as plain numbered SQL migrations** (`backend/migrations/001_*.sql`), applied at startup by a small migrator that records them in a `schema_migrations` table. No ORM.
   - `ships(mmsi PK, name, first_seen, last_seen)`, upserted.
   - `positions(time, mmsi, geom geography(Point, 4326), sog, cog, true_heading, nav_status)`:
     - a hypertable with 1-day chunks;
     - index on `(mmsi, time DESC)`;
     - compression after 1 day, segmented by `mmsi`;
     - retention of 30 days (configurable).
   - Only **accepted** positions are stored: those that passed the out-of-order and jump filters, i.e. what the map shows.
3. **Writer task** (`backend/src/minicop/recorder.py`)
   - Fed by the state task through a **bounded queue**; enqueuing never waits, so a slow database can never slow the live map.
   - Writes in batches: every 1 s or every 1000 rows, using PostgreSQL `COPY` (asyncpg).
   - **If the database is down:** reconnect with backoff, keep buffering, and when the buffer is full drop the oldest rows and count them.
     - The live picture always has priority over the archive.
   - **`/health`** gains `db_connected`, `db_written`, `db_queued` and `db_dropped`.
4. **Optional by configuration.** If `DATABASE_URL` is not set, recording is off and everything works as today. This covers development without Docker, and the existing tests.
5. **Tests**
   - Unit (no database): batching by size and by time, dropping the oldest rows on overflow, the counters.
   - Integration, against a **real** TimescaleDB:
     - migrations apply cleanly and twice (idempotent);
     - a batch is written and read back;
     - retention and compression policies are in place.
   - Runs in CI as a service container, and locally with Docker.
6. **Guardrails:** the CI Docker smoke test also checks that the backend reports `db_connected: true` and that rows are being written.

## Out of scope
- Reading routes from the database, or any UI change (phase 13).
- User-drawn areas (phase 14).
- Storing alerts, backups, and hosting.

## Acceptance
- `docker compose up --build`: positions are recorded.
- After an hour on live data, the phase summary reports the row count, the rows per second and the disk use.
- `docker compose restart` keeps all data.
- Stopping the database while the service runs:
  - the live map keeps working;
  - `/health` shows the problem;
  - after the database comes back, recording resumes, and the dropped count is reported.
- All guardrails and CI pass.

## Note: in-process queue, not a message broker
The queue between the state task and the writer is an `asyncio.Queue` inside the process, like the one between ingestion and state. It exists so that a slow database never blocks the live map.

A message broker (Kafka, RabbitMQ, NATS) is a separate service. It only pays off with several processes or sources: for example sensor fusion with AIS, radar and drone feeds, and several consumers. It is a candidate for a later phase (15), not part of this one.
