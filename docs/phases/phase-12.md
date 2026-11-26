# Phase 12 — Record every position in a database

## Done
- **Database service** in Docker Compose: `timescale/timescaledb-ha:pg17.12-ts2.32.1` (PostgreSQL 17 + TimescaleDB 2.32 + PostGIS).
  - Named volume `pgdata`.
  - Healthcheck.
  - The password comes from `.env` (`POSTGRES_PASSWORD`); compose stops with a clear message if it is missing.
  - Not published to the host.
- **`backend/migrations/001_positions.sql`**
  - `ships` (upserted).
  - `positions`, a hypertable with 1-day chunks and an `(mmsi, time DESC)` index.
  - Compression after 1 day, segmented by ship.
  - `geom geography(Point)` generated from `lat`/`lon`.
- **`db.py`**: a small migrator (numbered `.sql` files, recorded in `schema_migrations`, one transaction each) and `set_retention()`. Retention comes from `MINICOP_RETENTION_DAYS`, default 30, and is re-applied at every start so a change takes effect.
- **`recorder.py`**
  - `RecordBuffer`: a bounded FIFO; dropping the oldest rows on overflow is counted; rows from a failed write are put back in order.
  - `Recorder`: connects, migrates, writes batches (1 s or 1000 rows) with `COPY`, and reconnects with backoff.
  - The state task calls `enqueue()`, which never waits.
- **`/health`**: `db_enabled`, `db_connected`, `db_written`, `db_queued` and `db_dropped`.
- **Optional:** without `DATABASE_URL`, nothing changes (development without Docker, unit tests).
- **Tests**: 6 unit tests for the buffer and 3 integration tests against a real TimescaleDB:
  - migrations are idempotent and the hypertable exists;
  - the compression and retention policies exist, and changing retention replaces the policy;
  - positions and ships are written and read back, with the geometry derived from lat/lon.
  CI runs them with a service container.
- **CI docker job**: the stack now includes the database, and the job asserts `db_connected`.

## Decisions
- **TimescaleDB + PostGIS, not Redis.** Redis is an in-memory cache and bus; the live state already lives in memory. What was missing was durable, queryable history. See the spec.
- **An in-process `asyncio.Queue`/buffer, not a broker.** It exists so a slow database never blocks the live map. A broker (Kafka, NATS, ...) only pays off with several processes or sources; it is a later candidate (see the spec note).
- **`lat`/`lon` columns plus a generated `geom`.** `COPY` can't call PostGIS functions, so the recorder writes plain numbers and the database derives the geography.
- **Only accepted positions are stored**: what the map shows, after the out-of-order and jump filters.
- **The image tag is pinned exactly.** The non-`oss` image is used, because compression is a Timescale License feature (free to use, not open source).
- **No ORM.** The schema is plain SQL that anyone can read.

## Verified (dev container)
- 126 tests pass (3 against a real TimescaleDB).
- **Outage test**, with a fake feed of 20 ships at 1 report/s and recording on:
  - while the database was stopped, the live map kept its 20 ships, `/health` showed `db_connected: false` and the queue grew to 420;
  - after a restart the recorder reconnected by itself and caught up: 1200 written, queue 0, **0 dropped**.
- **Full compose stack**:
  - the database is healthy and the migration applied;
  - the backend reports `db_connected: true`;
  - a row survived `docker compose down` / `up`.
- **Live run (developer's Mac, area `portugal`, 33.5 min at night, 22:19–22:53 UTC):**
  - **623 rows from 127 ships = 0.31 rows/s**, about 5 points per ship in half an hour;
  - **208 kB**, about 330 bytes per row before compression. That includes the index and fixed table overhead, so it falls as the table grows. Compression only touches chunks older than 1 day, so it isn't measured yet;
  - **0 dropped**, 0 queued.
  - **Projection at this rate:** about 27 k rows/day and well under 1 GB for 30 days before compression. The database is nowhere near a limit.
  - **The feed is far sparser than the spec's estimate** (20–40 rows/s). Three reasons:
    - **night**: most fishing boats are moored, and moored ships report only every 3 min;
    - **the free aisstream terrestrial coverage of Portugal is thin**: even a moored ship should give about 11 points in 33 min, and we see about 5;
    - **we subscribe to `PositionReport` only (Class A)**, so small vessels (Class B) are not received at all. That is proposed as phase 13.
  - **Consequence for routes:** few points per ship. Routes will have long straight gaps, and the UI should show the actual reported points.
- **Pipeline counters added to `/health`**, so "the feed sends little" can be told apart from "we lose data":
  - `frames_received`: every frame from aisstream;
  - `positions_parsed`: frames that became a usable position;
  - `positions_accepted`: positions accepted by the state;
  - `rejected_out_of_order` and `rejected_jumps`: positions the state rejected.

  Each step should be close to the previous one, and `db_written` close to `positions_accepted`.
- **Counters on live data** (developer's Mac, area `portugal`, about 13.5 min, 23:11–23:24 UTC):

  | Step | Count |
  |---|---|
  | `frames_received` | 197 |
  | `positions_parsed` | 196 (the 1 missing is the `SubscriptionConfirmation` frame) |
  | `positions_accepted` | 196 (0 out of order, 0 jumps) |
  | `db_written` | 196 (0 queued, 0 dropped) |

  **No loss anywhere in the pipeline.** The low rate (about 0.24 frames/s for the whole coast at night) is the source, not our code.
  This was not in the spec; it was added after the live run showed fewer rows than expected.

## Deviation from the spec
- The pipeline counters above were added to `/health` (not in the spec), to explain the low live rate.
- The CI docker job checks `db_connected`, but **not that rows are written**: with a dummy API key there is no AIS feed. Writing is covered by the integration test and by the outage test above.

## What the agent got wrong
| Problem | How it was caught | What changed |
|---|---|---|
| `RecordBuffer` kept the *latest* name per ship, so a ship whose last report had no name was written with an empty name. The SQL upsert only protects names already in the table. The unit tests didn't cover it. | The integration test against the real database. | Keep the last *known* name; new unit test. |
| The integration tests connected exactly once and failed with "connection reset": the timescaledb-ha image restarts its server once during first-time init, after `pg_isready` already says ready. | Running the tests right after starting a fresh container. | The tests retry connecting for up to 30 s. The service was already fine: the recorder reconnects with backoff. |
| Diagnosed that as "`pg_isready` uses the Unix socket, use TCP". **Wrong**: tested, and TCP also reports ready during the temporary init server. | Probing both every 0.5 s on a fresh container before changing anything. | No healthcheck change; the retry above. Lesson: test the hypothesis before applying the fix. |

## How to run
Add `POSTGRES_PASSWORD=<anything strong>` to `.env`, then `docker compose up --build`.
- `curl localhost:8080/api/health` shows `db_written` growing.
- Inspect the data: `docker compose exec db psql -U postgres -d minicop -c "select count(*) from positions"`.
- Integration tests locally: start a TimescaleDB, then run `TEST_DATABASE_URL=postgresql://postgres:<pw>@localhost:5432/<db> pytest`.
