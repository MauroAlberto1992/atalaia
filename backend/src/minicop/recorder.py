"""Recorder: writes every accepted position to the database, in batches.

The state task calls `enqueue()`, which never waits, so a slow or absent
database can never slow down the live map. A separate task drains the buffer
and writes with PostgreSQL COPY.

When the database is down, rows keep accumulating up to `max_buffered`; past
that the *oldest* rows are dropped and counted. The live picture always has
priority over the archive.
"""

import asyncio
import contextlib
import logging
import time
from collections import deque
from datetime import datetime

import asyncpg

from minicop.db import migrate, set_retention
from minicop.events import Track
from minicop.ingest import Backoff

log = logging.getLogger(__name__)

BATCH_ROWS = 1000  # write as soon as this many rows are waiting...
BATCH_SECONDS = 1.0  # ...or at least this often
MAX_BUFFERED = 200_000  # ~1-2 h of a whole-coast feed while the DB is down

PositionRow = tuple[datetime, int, float, float, float, float, int, int]
POSITION_COLUMNS = ["time", "mmsi", "lat", "lon", "sog", "cog", "true_heading", "nav_status"]


class RecordBuffer:
    """Bounded FIFO of rows waiting to be written. Pure, no I/O."""

    def __init__(self, max_rows: int = MAX_BUFFERED) -> None:
        self._rows: deque[PositionRow] = deque(maxlen=max_rows)
        self._names: dict[int, tuple[str, datetime]] = {}  # latest name per ship
        self.dropped = 0

    def add(self, track: Track) -> None:
        if len(self._rows) == self._rows.maxlen:
            self.dropped += 1  # deque drops the oldest on append when full
        self._rows.append(
            (
                track.last_seen,
                track.mmsi,
                track.latitude,
                track.longitude,
                track.sog,
                track.cog,
                track.true_heading,
                track.navigational_status,
            )
        )
        # Keep the last *known* name: many reports carry no name, and an empty
        # one must not replace a real one (the SQL upsert only protects names
        # already in the table, not a ship first written in this batch).
        previous = self._names.get(track.mmsi)
        name = track.ship_name or (previous[0] if previous else "")
        self._names[track.mmsi] = (name, track.last_seen)

    def take(self, n: int) -> tuple[list[PositionRow], dict[int, tuple[str, datetime]]]:
        """Remove up to n oldest rows, plus the ship names seen so far."""
        rows = [self._rows.popleft() for _ in range(min(n, len(self._rows)))]
        names, self._names = self._names, {}
        return rows, names

    def put_back(self, rows: list[PositionRow], names: dict[int, tuple[str, datetime]]) -> None:
        """A write failed: return the rows to the front, keeping order. If new
        rows arrived meanwhile and there is no room, the oldest are dropped."""
        for row in reversed(rows):
            if len(self._rows) == self._rows.maxlen:
                self.dropped += 1
                continue  # the buffer is full of newer rows: drop this old one
            self._rows.appendleft(row)
        for mmsi, value in names.items():
            self._names.setdefault(mmsi, value)

    def __len__(self) -> int:
        return len(self._rows)


class Recorder:
    def __init__(self, dsn: str, retention_days: int, max_buffered: int = MAX_BUFFERED) -> None:
        self._dsn = dsn
        self._retention_days = retention_days
        self.buffer = RecordBuffer(max_buffered)
        self._wake = asyncio.Event()
        self.connected = False
        self.written = 0

    def enqueue(self, track: Track) -> None:
        """Called by the state task. Never waits."""
        self.buffer.add(track)
        if len(self.buffer) >= BATCH_ROWS:
            self._wake.set()

    async def run(self) -> None:
        """Connect, migrate, then write batches forever (until cancelled)."""
        backoff = Backoff()
        while True:
            try:
                conn = await asyncpg.connect(self._dsn, timeout=10)
                try:
                    await migrate(conn)
                    await set_retention(conn, self._retention_days)
                    self.connected = True
                    backoff.reset()
                    log.info("Recorder connected to the database")
                    await self._write_loop(conn)
                finally:
                    self.connected = False
                    await conn.close(timeout=5)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # connection refused, DB restart, ...
                log.warning("Recorder database error: %r", exc)
            delay = backoff.next()
            log.info("Recorder reconnecting in %.1f s (%d rows buffered)", delay, len(self.buffer))
            await asyncio.sleep(delay)

    async def _write_loop(self, conn: asyncpg.Connection) -> None:
        while True:
            # Wait for a full batch or BATCH_SECONDS, whichever comes first.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), BATCH_SECONDS)
            self._wake.clear()
            while len(self.buffer):
                rows, names = self.buffer.take(BATCH_ROWS)
                started = time.monotonic()
                try:
                    await self._write(conn, rows, names)
                except BaseException:
                    self.buffer.put_back(rows, names)  # nothing is lost on a failed write
                    raise
                self.written += len(rows)
                log.debug("Wrote %d rows in %.3f s", len(rows), time.monotonic() - started)

    @staticmethod
    async def _write(
        conn: asyncpg.Connection,
        rows: list[PositionRow],
        names: dict[int, tuple[str, datetime]],
    ) -> None:
        async with conn.transaction():
            await conn.copy_records_to_table("positions", records=rows, columns=POSITION_COLUMNS)
            if names:
                # Keep a known name if a report came without one; widen the
                # first/last seen window.
                await conn.executemany(
                    """
                    INSERT INTO ships (mmsi, name, first_seen, last_seen)
                    VALUES ($1, $2, $3, $3)
                    ON CONFLICT (mmsi) DO UPDATE SET
                        name = COALESCE(NULLIF(EXCLUDED.name, ''), ships.name),
                        first_seen = LEAST(ships.first_seen, EXCLUDED.first_seen),
                        last_seen = GREATEST(ships.last_seen, EXCLUDED.last_seen)
                    """,
                    [(mmsi, name, seen) for mmsi, (name, seen) in names.items()],
                )
