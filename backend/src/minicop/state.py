"""In-memory state: the single owner of the MMSI -> Track map.

Pure logic, no asyncio or I/O, so it is trivial to test. The async plumbing
that feeds it lives in api.py.
"""

from minicop.events import PositionEvent, Track


class TrackStore:
    def __init__(self) -> None:
        self._tracks: dict[int, Track] = {}

    def apply(self, event: PositionEvent) -> Track | None:
        """Update the ship's track. Returns the new Track, or None if the event
        is older than what we already have (AIS can arrive out of order)."""
        current = self._tracks.get(event.mmsi)
        if current is not None and event.received_at <= current.last_seen:
            return None
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
        )
        self._tracks[event.mmsi] = track
        return track

    def snapshot(self) -> list[Track]:
        return list(self._tracks.values())

    def __len__(self) -> int:
        return len(self._tracks)
