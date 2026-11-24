"""Per-ship route history with running distance, filtered against GPS noise."""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from minicop.geo import haversine_nm

log = logging.getLogger(__name__)

MAX_POINTS = 2000
JITTER_NM = 10 / 1852  # 10 m: below this, the ship has not really moved
MAX_SPEED_KN = 60  # faster than any ship we expect: treat as a GPS glitch
MAX_CONSECUTIVE_JUMPS = 3  # after this many, believe the new position (see add)


@dataclass
class _Point:
    lat: float
    lon: float
    t: datetime
    dist_from_prev_nm: float  # kept so it can be subtracted when the point before is evicted


class AddResult(Enum):
    ADDED = "added"
    JITTER = "jitter"  # too close to the last point: not part of the route
    JUMP = "jump"  # impossible speed: rejected as a glitch


class HistoryPoint(BaseModel):
    latitude: float
    longitude: float
    t: datetime


class HistoryStats(BaseModel):
    distance_nm: float
    duration_s: float
    avg_speed_kn: float


class ShipHistory:
    def __init__(self, max_points: int = MAX_POINTS) -> None:
        self._points: deque[_Point] = deque()
        self._max_points = max_points
        self._distance_nm = 0.0
        self._jumps = 0

    def add(self, lat: float, lon: float, t: datetime) -> AddResult:
        if not self._points:
            self._points.append(_Point(lat, lon, t, 0.0))
            return AddResult.ADDED

        last = self._points[-1]
        d = haversine_nm(last.lat, last.lon, lat, lon)
        if d < JITTER_NM:
            return AddResult.JITTER

        hours = (t - last.t).total_seconds() / 3600
        if hours <= 0 or d / hours > MAX_SPEED_KN:
            self._jumps += 1
            if self._jumps < MAX_CONSECUTIVE_JUMPS:
                log.info("Rejected position jump: %.2f nm in %.0f s", d, hours * 3600)
                return AddResult.JUMP
            # Several "glitches" in a row agree with each other, so it was the
            # old position that was wrong (or a long gap). Accept the new one,
            # but don't count the jump as distance travelled.
            d = 0.0

        self._jumps = 0
        self._points.append(_Point(lat, lon, t, d))
        self._distance_nm += d
        if len(self._points) > self._max_points:
            self._points.popleft()
            # The new first point no longer has a predecessor in the history.
            first = self._points[0]
            self._distance_nm -= first.dist_from_prev_nm
            first.dist_from_prev_nm = 0.0
        return AddResult.ADDED

    def stats(self) -> HistoryStats:
        if len(self._points) < 2:
            return HistoryStats(distance_nm=0.0, duration_s=0.0, avg_speed_kn=0.0)
        duration_s = (self._points[-1].t - self._points[0].t).total_seconds()
        avg = self._distance_nm / (duration_s / 3600) if duration_s > 0 else 0.0
        return HistoryStats(distance_nm=self._distance_nm, duration_s=duration_s, avg_speed_kn=avg)

    def points(self) -> list[HistoryPoint]:
        return [HistoryPoint(latitude=p.lat, longitude=p.lon, t=p.t) for p in self._points]
