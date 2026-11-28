"""Areas drawn by operators on the map (phase 16): validation and storage.

Validation is pure logic; storage is plain SQL over asyncpg. The state task is
still the only writer of the live zone list (see api.py): the API validates and
stores, then puts a ZoneAdded / ZoneRemoved event on the queue.
"""

import json
from typing import Literal

import asyncpg
from pydantic import BaseModel, Field, field_validator

from minicop.config import Area, Corner
from minicop.zones import Zone

MAX_VERTICES = 50


class UserZoneIn(BaseModel):
    """What the browser sends when an operator finishes drawing."""

    # No "/" (DELETE /zones/{name} could never match it) and no control
    # characters; spaces around are stripped before the length check, so a
    # blank name is refused (it used to be saved as "" and break the reload).
    name: str = Field(min_length=1, max_length=60, pattern=r"^[^/\x00-\x1f\x7f]+$")
    kind: Literal["restricted", "watch"]
    polygon: list[Corner] = Field(min_length=3, max_length=MAX_VERTICES)

    @field_validator("name", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    def to_zone(self) -> Zone:
        # Both kinds alert on entry; they differ in colour (and meaning) only.
        return Zone(
            name=self.name,
            kind=self.kind,
            alert_on_entry=True,
            polygon=self.polygon,
            source="user",
        )


def _cross(o: Corner, a: Corner, b: Corner) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(p: Corner, a: Corner, b: Corner) -> bool:
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def _segments_touch(p1: Corner, p2: Corner, q1: Corner, q2: Corner) -> bool:
    """Two segments cross or touch (a vertex lying on the other segment counts:
    that pinches the polygon). Flat lat/lon is fine at the size of a drawn area."""
    d1, d2 = _cross(q1, q2, p1), _cross(q1, q2, p2)
    d3, d4 = _cross(p1, p2, q1), _cross(p1, p2, q2)
    if d1 * d2 < 0 and d3 * d4 < 0:
        return True
    return (
        (d1 == 0 and _on_segment(p1, q1, q2))
        or (d2 == 0 and _on_segment(p2, q1, q2))
        or (d3 == 0 and _on_segment(q1, p1, p2))
        or (d4 == 0 and _on_segment(q2, p1, p2))
    )


def _area_deg2(polygon: list[Corner]) -> float:
    """Shoelace area in square degrees (only compared with ~0)."""
    n = len(polygon)
    return (
        abs(
            sum(
                polygon[i][1] * polygon[(i + 1) % n][0] - polygon[(i + 1) % n][1] * polygon[i][0]
                for i in range(n)
            )
        )
        / 2
    )


def _in_area(lat: float, lon: float, area: Area) -> bool:
    return any(lo[0] <= lat <= hi[0] and lo[1] <= lon <= hi[1] for lo, hi in area.boxes)


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
            if _segments_touch(*edges[i], *edges[j]):
                return "The area's edges cross or touch each other; draw it without crossings"
    # After the crossing check (a symmetric bow tie also has zero signed area).
    # ~100 m2 at these latitudes: points in a line (or nearly) enclose nothing.
    if _area_deg2(polygon) < 1e-8:
        return "The area's points are in a line; draw an area that encloses something"
    if area is not None:
        for lat, lon in polygon:
            if not _in_area(lat, lon, area):
                return f"Point {lat:.4f}, {lon:.4f} is outside the monitored area ({area.name})"
        # With several boxes, an edge between two boxes can leave them: sample it.
        for a, b in edges:
            for k in range(1, 20):
                f = k / 20
                lat, lon = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
                if not _in_area(lat, lon, area):
                    return (
                        f"An edge leaves the monitored area ({area.name}) near {lat:.4f}, {lon:.4f}"
                    )
    return None


async def load_user_zones(pool: asyncpg.Pool) -> list[Zone]:
    rows = await pool.fetch("SELECT name, kind, polygon FROM user_zones ORDER BY created_at")
    # Built straight from the stored rows, not through UserZoneIn: input rules
    # that tighten later must not make an already saved area fail to load.
    return [
        Zone(
            name=r["name"],
            kind=r["kind"],
            alert_on_entry=True,
            polygon=json.loads(r["polygon"]),
            source="user",
        )
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
