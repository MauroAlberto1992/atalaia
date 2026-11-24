"""In-memory state: the single owner of the MMSI -> Track map and each ship's history.

Pure logic, no asyncio or I/O, so it is trivial to test. The async plumbing
that feeds it lives in api.py.
"""

from minicop.events import PositionEvent, Track
from minicop.history import AddResult, ShipHistory


class TrackStore:
    def __init__(self) -> None:
        self._tracks: dict[int, Track] = {}
        self._history: dict[int, ShipHistory] = {}

    def apply(self, event: PositionEvent) -> Track | None:
        """Update the ship's track. Returns the new Track, or None if nothing
        changed: the event is older than what we have (AIS can arrive out of
        order) or its position was rejected as a GPS jump."""
        current = self._tracks.get(event.mmsi)
        if current is not None and event.received_at <= current.last_seen:
            return None

        history = self._history.setdefault(event.mmsi, ShipHistory())
        if history.add(event.latitude, event.longitude, event.received_at) is AddResult.JUMP:
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
            distance_nm=stats.distance_nm,
            avg_speed_kn=stats.avg_speed_kn,
        )
        self._tracks[event.mmsi] = track
        return track

    def history(self, mmsi: int) -> ShipHistory | None:
        return self._history.get(mmsi)

    def snapshot(self) -> list[Track]:
        return list(self._tracks.values())

    def __len__(self) -> int:
        return len(self._tracks)
