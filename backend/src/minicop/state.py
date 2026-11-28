"""In-memory state: the single owner of the MMSI -> Track map and each ship's history.

Pure logic, no asyncio or I/O, so it is trivial to test. The async plumbing
that feeds it lives in api.py.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from minicop.bathymetry import Bathymetry
from minicop.events import PositionEvent, StaticEvent, Track
from minicop.history import AddResult, ShipHistory
from minicop.ship_types import ship_type_label

# Class A ships report every 2-10 s under way and every 3 min when moored,
# so 10 min of silence is abnormal. After 1 h we forget the ship entirely,
# otherwise memory would grow forever as ships pass through the area.
STALE_AFTER = timedelta(minutes=10)
REMOVE_AFTER = timedelta(minutes=60)
# Static data can arrive before (or without) any position: keep at most this
# many ships' static data, forgetting the oldest first.
MAX_STATIC = 20_000


@dataclass
class SweepResult:
    stale: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)
    removed_tracks: list[Track] = field(default_factory=list)  # last known state


@dataclass
class StaticInfo:
    ship_type: int | None = None
    draught_m: float | None = None


class TrackStore:
    def __init__(self, bathymetry: Bathymetry | None = None) -> None:
        self._tracks: dict[int, Track] = {}
        self._bathymetry = bathymetry
        self._static: dict[int, StaticInfo] = {}
        self._history: dict[int, ShipHistory] = {}
        # Times of rejected position jumps per ship, for spoofing detection.
        self._jumps: dict[int, deque[datetime]] = {}
        # Counters for /health: why reports did or didn't change a track.
        self.accepted = 0
        self.out_of_order = 0
        self.jumps_rejected = 0

    def apply(self, event: PositionEvent) -> Track | None:
        """Update the ship's track. Returns the new Track, or None if nothing
        changed: the event is older than what we have (AIS can arrive out of
        order) or its position was rejected as a GPS jump."""
        current = self._tracks.get(event.mmsi)
        if current is not None and event.received_at <= current.last_seen:
            self.out_of_order += 1
            return None

        history = self._history.setdefault(event.mmsi, ShipHistory())
        if history.add(event.latitude, event.longitude, event.received_at) is AddResult.JUMP:
            self._jumps.setdefault(event.mmsi, deque(maxlen=50)).append(event.received_at)
            self.jumps_rejected += 1
            return None  # don't move the ship on the map to a glitch position
        # JITTER still updates the track: speed, status and last_seen are fresh.
        stats = history.stats()

        track = Track(
            mmsi=event.mmsi,
            # Keep a known name if this report came without one.
            ship_name=event.ship_name or (current.ship_name if current else ""),
            latitude=event.latitude,
            longitude=event.longitude,
            sog=event.sog,
            cog=event.cog,
            true_heading=event.true_heading,
            navigational_status=event.navigational_status,
            last_seen=event.received_at,
            ais_class=event.ais_class,
            # A new AIS report must not erase the last sensor confirmation.
            sensor_seen=current.sensor_seen if current else None,
            distance_nm=stats.distance_nm,
            avg_speed_kn=stats.avg_speed_kn,
            **self._context(event.mmsi, event.latitude, event.longitude, current),
        )
        self._tracks[event.mmsi] = track
        self.accepted += 1
        return track

    def _context(
        self, mmsi: int, lat: float, lon: float, current: Track | None = None
    ) -> dict[str, object]:
        """Declared static data and the depth here (phase 17a). If the static
        store has evicted this ship, keep what its track already had."""
        info = self._static.get(mmsi) or StaticInfo(
            current.ship_type if current else None, current.draught_m if current else None
        )
        return {
            "ship_type": info.ship_type,
            "ship_type_label": ship_type_label(info.ship_type),
            "draught_m": info.draught_m,
            "depth_m": self._bathymetry.depth_m(lat, lon) if self._bathymetry else None,
        }

    def apply_static(self, event: StaticEvent) -> Track | None:
        """Remember a ship's declared type/draught. Returns the updated Track if
        the ship is on the map and something changed, else None. A message
        without a draught (Class B) does not erase a known one."""
        info = self._static.pop(event.mmsi, StaticInfo())  # re-insert: newest last
        new = StaticInfo(
            ship_type=event.ship_type if event.ship_type is not None else info.ship_type,
            draught_m=event.draught_m if event.draught_m is not None else info.draught_m,
        )
        self._static[event.mmsi] = new
        while len(self._static) > MAX_STATIC:
            del self._static[next(iter(self._static))]
        track = self._tracks.get(event.mmsi)
        if track is None or new == info:
            return None
        updated = track.model_copy(
            update={
                "ship_type": new.ship_type,
                "ship_type_label": ship_type_label(new.ship_type),
                "draught_m": new.draught_m,
            }
        )
        self._tracks[event.mmsi] = updated
        return updated

    def sweep(self, now: datetime) -> SweepResult:
        """Mark silent ships stale and remove long-silent ones (with their history).
        Only reports changes: a ship already stale is not reported again.
        A stale ship that reports again becomes fresh through apply(), since
        the new Track is built with stale=False."""
        result = SweepResult()
        for mmsi, track in list(self._tracks.items()):
            silence = now - track.last_seen
            if silence >= REMOVE_AFTER:
                del self._tracks[mmsi]
                self._history.pop(mmsi, None)
                self._jumps.pop(mmsi, None)
                result.removed.append(mmsi)
                result.removed_tracks.append(track)
            elif silence >= STALE_AFTER and not track.stale:
                self._tracks[mmsi] = track.model_copy(update={"stale": True})
                result.stale.append(mmsi)
        return result

    def mark_sensor(self, mmsi: int, t: datetime) -> Track | None:
        """A sensor detection was associated with this AIS track (phase 15)."""
        track = self._tracks.get(mmsi)
        if track is None:
            return None
        updated = track.model_copy(update={"sensor_seen": t})
        self._tracks[mmsi] = updated
        return updated

    def get(self, mmsi: int) -> Track | None:
        return self._tracks.get(mmsi)

    def jumps_since(self, mmsi: int, since: datetime) -> int:
        """How many position jumps were rejected for this ship since `since`."""
        return sum(1 for t in self._jumps.get(mmsi, ()) if t >= since)

    def history(self, mmsi: int) -> ShipHistory | None:
        return self._history.get(mmsi)

    def snapshot(self) -> list[Track]:
        return list(self._tracks.values())

    def __len__(self) -> int:
        return len(self._tracks)
