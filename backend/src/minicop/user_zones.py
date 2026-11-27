"""Areas drawn by operators on the map (phase 16): validation and storage.

Validation is pure logic; storage is plain SQL over asyncpg. The state task is
still the only writer of the live zone list (see api.py): the API validates and
stores, then puts a ZoneAdded / ZoneRemoved event on the queue.
"""

import json
from typing import Literal

import asyncpg
from pydantic import BaseModel, Field

from minicop.config import Area, Corner
from minicop.zones import Zone

MAX_VERTICES = 50


class UserZoneIn(BaseModel):
    """What the browser sends when an operator finishes drawing."""

    name: str = Field(min_length=1, max_length=60)
    kind: Literal["restricted", "watch"]
    polygon: list[Corner] = Field(min_length=3, max_length=MAX_VERTICES)

    def to_zone(self) -> Zone:
        # Both kinds alert on entry; they differ in colour (and meaning) only.
        return Zone(
            name=self.name.strip(),
            kind=self.kind,
            alert_on_entry=True,
            polygon=self.polygon,
            source="user",
        )


def _cross(o: Corner, a: Corner, b: Corner) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_cross(p1: Corner, p2: Corner, q1: Corner, q2: Corner) -> bool:
    """Proper crossing of two segments (touching at an end point does not count).
    Flat lat/lon is fine at the size of an area drawn on the map."""
    d1, d2 = _cross(q1, q2, p1), _cross(q1, q2, p2)
    d3, d4 = _cross(p1, p2, q1), _cross(p1, p2, q2)
    return d1 * d2 < 0 and d3 * d4 < 0


def polygon_problem(polygon: list[Corner], area: Area | None) -> str | None:
    """Why this polygon can't be an area, or None if it is fine."""
    n = len(polygon)
    if n < 3:
        return "An area needs at least 3 points"
    if len(set(polygon)) < 3:
        return "An area needs at least 3 different points"
    edges = [(polygon[i], polygon[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue  # neighbouring edges share a vertex
            if _segments_cross(*edges[i], *edges[j]):
                return "The area's edges cross each other; draw it without crossings"
    if area is not None:
        for lat, lon in polygon:
            if not any(lo[0] <= lat <= hi[0] and lo[1] <= lon <= hi[1] for lo, hi in area.boxes):
                return f"Point {lat:.4f}, {lon:.4f} is outside the monitored area ({area.name})"
    return None


async def load_user_zones(pool: asyncpg.Pool) -> list[Zone]:
    rows = await pool.fetch("SELECT name, kind, polygon FROM user_zones ORDER BY created_at")
    return [
        UserZoneIn(name=r["name"], kind=r["kind"], polygon=json.loads(r["polygon"])).to_zone()
        for r in rows
    ]


async def save_user_zone(pool: asyncpg.Pool, zone: Zone) -> None:
    await pool.execute(
        "INSERT INTO user_zones (name, kind, polygon) VALUES ($1, $2, $3::jsonb)",
        zone.name,
        zone.kind,
        json.dumps(zone.polygon),
    )


async def delete_user_zone(pool: asyncpg.Pool, name: str) -> None:
    await pool.execute("DELETE FROM user_zones WHERE name = $1", name)
