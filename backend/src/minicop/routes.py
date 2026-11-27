"""Routes from recorded history: pure logic, no database.

The AIS feed is sparse and uneven (about 30 reports per ship per hour, with
long silences), so a route is split into *segments* wherever two consecutive
points are far apart in time. Gaps are reported, never drawn as if the ship
had been seen crossing them.
"""

from datetime import datetime, timedelta

from pydantic import BaseModel

from minicop.history import ShipHistory

MAX_GAP = timedelta(minutes=30)  # longer than this between points = a gap
MAX_POINTS = 5000  # cap per request; more are thinned evenly by time


class RoutePoint(BaseModel):
    time: datetime
    lat: float
    lon: float
    sog: float
    cog: float


class RouteStats(BaseModel):
    points: int
    distance_nm: float  # within segments only: gaps are not counted as travel
    moving_time_s: float  # time covered by segments (gaps excluded)
    avg_speed_kn: float  # distance_nm / moving time
    longest_gap_s: float  # 0 if the route has a single segment


def thin(points: list[RoutePoint], cap: int = MAX_POINTS) -> tuple[list[RoutePoint], bool]:
    """Keep at most `cap` points, evenly spread by index (points are in time
    order), always keeping the first and the last. Returns (points, thinned)."""
    if len(points) <= cap:
        return points, False
    if cap < 2:
        return points[:cap], True
    step = (len(points) - 1) / (cap - 1)
    return [points[round(i * step)] for i in range(cap)], True


def split_segments(
    points: list[RoutePoint], max_gap: timedelta = MAX_GAP
) -> list[list[RoutePoint]]:
    """Split time-ordered points wherever consecutive points are > max_gap apart."""
    segments: list[list[RoutePoint]] = []
    for p in points:
        if segments and p.time - segments[-1][-1].time <= max_gap:
            segments[-1].append(p)
        else:
            segments.append([p])
    return segments


def route_stats(segments: list[list[RoutePoint]]) -> RouteStats:
    """Distance and speed per segment, using the same jitter and jump filters
    as the live history (phase 4), then summed. Gaps don't count as travel."""
    distance = 0.0
    moving_s = 0.0
    for seg in segments:
        history = ShipHistory(max_points=len(seg) + 1)  # no eviction
        for p in seg:
            history.add(p.lat, p.lon, p.time)
        distance += history.stats().distance_nm
        moving_s += (seg[-1].time - seg[0].time).total_seconds()
    gaps = [
        (b[0].time - a[-1].time).total_seconds()
        for a, b in zip(segments, segments[1:], strict=False)
    ]
    return RouteStats(
        points=sum(len(s) for s in segments),
        distance_nm=distance,
        moving_time_s=moving_s,
        avg_speed_kn=distance / (moving_s / 3600) if moving_s > 0 else 0.0,
        longest_gap_s=max(gaps, default=0.0),
    )
