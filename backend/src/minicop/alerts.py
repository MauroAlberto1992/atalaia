"""Alert rules. Pure logic, called by the state task (the single writer).

Rules:
- enter / exit: ship crosses the boundary of a zone with alert_on_entry.
- speeding: ship inside a zone goes faster than its max_speed_kn
  (once per visit, not on every report).
- dark: ship goes stale (stops transmitting) while inside any zone.
"""

from collections import deque
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from minicop.events import Track
from minicop.ports import PORT_MARGIN_NM
from minicop.zones import Zone

MAX_ALERTS = 200


class AlertKind(StrEnum):
    ENTER = "enter"
    EXIT = "exit"
    SPEEDING = "speeding"
    DARK = "dark"
    # Behavioural anomalies (anomalies.py), not tied to a zone.
    LOITERING = "loitering"
    RENDEZVOUS = "rendezvous"
    REAPPEARED = "reappeared"
    SPOOFING = "spoofing"
    # Sensor coverage (coverage.py): about our reception, not about a ship.
    COVERAGE_LOST = "coverage_lost"
    COVERAGE_RESTORED = "coverage_restored"
    # Sensor fusion (fusion.py): a sensor contact no AIS track explains.
    DARK_VESSEL = "dark_vessel"
    # A confirmed dark contact inside an area that alerts on entry (phase 16).
    DARK_IN_ZONE = "dark_in_zone"


class Alert(BaseModel):
    id: int
    kind: AlertKind
    mmsi: int
    ship_name: str
    zone: str | None = None  # None for behavioural anomalies
    at: datetime
    message: str  # human-readable reason, with the numbers behind it
    other_mmsi: int | None = None  # second ship, for rendezvous
    # Where it happened, for alerts not tied to an AIS ship (dark vessels).
    lat: float | None = None
    lon: float | None = None


class AlertEngine:
    def __init__(self, zones: list[Zone], max_alerts: int = MAX_ALERTS) -> None:
        # Own copy: user areas are added and removed here (phase 16), and the
        # caller's list is shared with other components.
        self._zones = list(zones)
        self._inside: dict[int, set[str]] = {}  # mmsi -> names of zones it is in
        self._speeding: set[tuple[int, str]] = set()  # already alerted this visit
        self._alerts: deque[Alert] = deque(maxlen=max_alerts)  # oldest drop off
        self._next_id = 1

    def record(
        self,
        kind: AlertKind,
        track: Track,
        at: datetime,
        message: str,
        zone: str | None = None,
        other_mmsi: int | None = None,
        lat: float | None = None,
        lon: float | None = None,
    ) -> Alert:
        """Create and keep an alert. Public so the anomaly detector shares the
        same id sequence and recent-alerts list."""
        alert = Alert(
            id=self._next_id,
            kind=kind,
            mmsi=track.mmsi,
            ship_name=track.ship_name or str(track.mmsi),
            zone=zone,
            at=at,
            message=message,
            other_mmsi=other_mmsi,
            lat=lat,
            lon=lon,
        )
        self._next_id += 1
        self._alerts.append(alert)
        return alert

    @property
    def zones(self) -> list[Zone]:
        return list(self._zones)

    def add_zone(self, zone: Zone, tracks: list[Track]) -> None:
        """Add an area while running. Ships already inside are recorded as
        inside without an alert: only a real entry after creation alerts.
        (At startup, by contrast, a ship first seen inside counts as entering.)"""
        self._zones.append(zone)
        for t in tracks:
            if not t.stale and zone.contains(t.latitude, t.longitude):
                self._inside.setdefault(t.mmsi, set()).add(zone.name)

    def remove_zone(self, name: str) -> None:
        """Remove an area without exit alerts: the area went, not the ships."""
        self._zones = [z for z in self._zones if z.name != name]
        for inside in self._inside.values():
            inside.discard(name)
        self._speeding = {k for k in self._speeding if k[1] != name}

    def zones_containing(self, lat: float, lon: float) -> list[Zone]:
        """Areas that alert on entry and contain this point (ports excluded)."""
        return [
            z for z in self._zones if z.alert_on_entry and z.kind != "port" and z.contains(lat, lon)
        ]

    def _raise(self, kind: AlertKind, track: Track, zone: str, at: datetime, message: str) -> Alert:
        return self.record(kind, track, at, message, zone=zone)

    def on_track(self, track: Track) -> list[Alert]:
        """Evaluate a ship's new position. Returns the alerts it raised."""
        out: list[Alert] = []
        now_inside = {z.name for z in self._zones if z.contains(track.latitude, track.longitude)}
        before = self._inside.get(track.mmsi, set())
        name = track.ship_name or str(track.mmsi)

        for zone in self._zones:
            entered = zone.name in now_inside and zone.name not in before
            left = zone.name in before and zone.name not in now_inside
            if left:
                self._speeding.discard((track.mmsi, zone.name))  # next visit can alert again
            if zone.alert_on_entry and entered:
                # A ship first seen already inside also counts as "entered".
                out.append(
                    self._raise(
                        AlertKind.ENTER,
                        track,
                        zone.name,
                        track.last_seen,
                        f"{name} entered {zone.name}",
                    )
                )
            if zone.alert_on_entry and left:
                out.append(
                    self._raise(
                        AlertKind.EXIT,
                        track,
                        zone.name,
                        track.last_seen,
                        f"{name} left {zone.name}",
                    )
                )
            if (
                zone.name in now_inside
                and zone.max_speed_kn is not None
                and track.sog > zone.max_speed_kn
                and (track.mmsi, zone.name) not in self._speeding
            ):
                self._speeding.add((track.mmsi, zone.name))
                out.append(
                    self._raise(
                        AlertKind.SPEEDING,
                        track,
                        zone.name,
                        track.last_seen,
                        f"{name} at {track.sog:.1f} kn in {zone.name} "
                        f"(limit {zone.max_speed_kn:g} kn)",
                    )
                )

        self._inside[track.mmsi] = now_inside
        return out

    def on_stale(self, track: Track, now: datetime) -> list[Alert]:
        """A ship stopped transmitting. Alert for each zone it was last seen in."""
        name = track.ship_name or str(track.mmsi)
        # Switching AIS off in port is normal: no "dark" alert in or next to a
        # port (same margin as for anomalies), even inside another zone.
        if any(
            z.kind == "port" and z.near(track.latitude, track.longitude, PORT_MARGIN_NM)
            for z in self._zones
        ):
            return []
        ports = {z.name for z in self._zones if z.kind == "port"}
        return [
            self._raise(AlertKind.DARK, track, zone, now, f"{name} went dark inside {zone}")
            for zone in sorted(self._inside.get(track.mmsi, set()) - ports)
        ]

    def on_removed(self, mmsi: int) -> None:
        """Forget a ship without raising exit alerts: it vanished, it didn't leave."""
        self._inside.pop(mmsi, None)
        self._speeding = {k for k in self._speeding if k[0] != mmsi}

    def recent(self) -> list[Alert]:
        """Newest first."""
        return list(reversed(self._alerts))
