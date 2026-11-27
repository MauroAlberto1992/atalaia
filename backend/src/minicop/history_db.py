"""Read side of the recorded history (phase 14). Plain SQL over asyncpg,
separate from the recorder: reading never touches the write path.

The pool is created lazily on the first request, so the API starts even if
the database is still coming up; a failed attempt is retried on the next request.
"""

import asyncio
from datetime import datetime, timedelta

import asyncpg
from pydantic import BaseModel

from minicop.routes import RoutePoint


class ShipSeen(BaseModel):
    mmsi: int
    name: str
    ais_class: str
    last_seen: datetime
    points: int  # positions recorded in the window


class HistoryDB:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def pool(self) -> asyncpg.Pool:
        async with self._lock:  # two first requests must not create two pools
            if self._pool is None:
                self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
            return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    async def route(self, mmsi: int, since: datetime) -> list[RoutePoint]:
        """Every recorded position of one ship since `since`, oldest first.
        Uses the (mmsi, time DESC) index; only chunks in the window are read."""
        pool = await self.pool()
        rows = await pool.fetch(
            """
            SELECT time, lat, lon, sog, cog
            FROM positions
            WHERE mmsi = $1 AND time >= $2
            ORDER BY time
            """,
            mmsi,
            since,
        )
        return [RoutePoint(**dict(r)) for r in rows]

    async def ships(self, since: datetime, limit: int = 500) -> list[ShipSeen]:
        """Ships with positions since `since`, most recently seen first,
        including ships no longer in the live state."""
        pool = await self.pool()
        rows = await pool.fetch(
            """
            SELECT p.mmsi,
                   COALESCE(s.name, '') AS name,
                   -- the class of the latest position in the window
                   (array_agg(p.ais_class ORDER BY p.time DESC))[1] AS ais_class,
                   max(p.time) AS last_seen,
                   count(*) AS points
            FROM positions p
            LEFT JOIN ships s ON s.mmsi = p.mmsi
            WHERE p.time >= $1
            GROUP BY p.mmsi, s.name
            ORDER BY last_seen DESC
            LIMIT $2
            """,
            since,
            limit,
        )
        return [ShipSeen(**dict(r)) for r in rows]


def window_start(now: datetime, hours: int) -> datetime:
    return now - timedelta(hours=hours)
