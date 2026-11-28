"""Behavioural anomaly detection: behaviour that doesn't fit, anywhere.

Pure logic, called by the state task (the single writer), like AlertEngine.
Every detector is an explainable rule: the alert message carries the numbers
that made it fire, so an operator can judge it. Thresholds come from
config/anomalies.toml.

Detectors:
- loitering: keeps moving but stays in a small area, away from ports;
- rendezvous: two ships close together and slow, away from ports, for a while;
- reappeared: a ship reports again after a long AIS gap;
- spoofing: repeated physically impossible position jumps.
Each fires once per episode, and re-arms when the condition ends.
"""

import math
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from minicop.alerts import Alert, AlertEngine, AlertKind
from minicop.config import BACKEND_DIR
from minicop.events import PositionEvent, Track
from minicop.geo import haversine_nm
from minicop.history import ShipHistory
from minicop.ports import PORT_MARGIN_NM
from minicop.zones import Zone

DEFAULT_ANOMALIES_FILE = BACKEND_DIR / "config" / "anomalies.toml"

# Rendezvous partners must have reported recently: an old position says
# nothing about where the other ship is now.
PARTNER_MAX_AGE = timedelta(minutes=5)
# How long to remember a ship's last position after it is removed from the
# state, so a reappearance after a long gap can still be measured.
LAST_SEEN_MEMORY = timedelta(hours=24)
# Grid cell size in degrees for the rendezvous neighbour search. One cell must
# be at least the rendezvous distance (0.3 nm) in both directions:
# 0.01° of latitude is 0.6 nm, 0.01° of longitude is 0.48 nm at 37°N
# and still 0.45 nm at 42°N.
GRID_DEG = 0.01
# AIS navigational status "moored": two ships moored together is not a
# rendezvous. "At anchor" (1) still counts: transfers are often done at anchor.
MOORED = 5


class AnomalyConfig(BaseModel):
    loiter_window_min: float
    loiter_min_travel_nm: float
    loiter_max_radius_nm: float
    rendezvous_max_distance_nm: float
    rendezvous_max_speed_kn: float
    rendezvous_min_duration_min: float
    gap_min_min: float
    spoof_jumps: int
    spoof_window_min: float


def load_anomaly_config(path: Path = DEFAULT_ANOMALIES_FILE) -> AnomalyConfig:
    with path.open("rb") as f:
        return AnomalyConfig(**tomllib.load(f)["anomalies"])


Cell = tuple[int, int]


def cell_of(lat: float, lon: float) -> Cell:
    return math.floor(lat / GRID_DEG), math.floor(lon / GRID_DEG)


class AnomalyDetector:
    def __init__(self, config: AnomalyConfig, zones: list[Zone], alerts: AlertEngine) -> None:
        self.cfg = config
        self._ports = [z for z in zones if z.kind == "port"]
        self._alerts = alerts  # shared id sequence and recent-alerts list

        self._latest: dict[int, Track] = {}  # latest track per ship
        self._last_seen: dict[int, Track] = {}  # survives removal, for gaps
        self._loitering: set[int] = set()  # ships in an alerted loiter episode
        self._spoofing: set[int] = set()  # ships in an alerted spoofing episode

        # Rendezvous: spatial grid + per-pair state.
        self._cell: dict[int, Cell] = {}
        self._grid: dict[Cell, set[int]] = {}
        self._close_since: dict[tuple[int, int], datetime] = {}
        self._rdv_alerted: set[tuple[int, int]] = set()

    # ---- entry points (called by the state task) ---------------------------

    def on_track(
        self, track: Track, history: ShipHistory | None, silence_was_coverage: bool = False
    ) -> list[Alert]:
        """A ship's track was updated (an accepted position).
        `silence_was_coverage`: its last silence was part of a coverage gap,
        so coming back is not a 'reappeared' anomaly."""
        out: list[Alert] = []
        if not silence_was_coverage:
            out += self._check_reappeared(track)
        self._latest[track.mmsi] = track
        self._last_seen[track.mmsi] = track
        self._move_in_grid(track)
        if history is not None:
            out += self._check_loitering(track, history)
        out += self._check_rendezvous(track)
        return out

    def on_position(self, event: PositionEvent, jumps_in_window: int) -> list[Alert]:
        """Every position report, accepted or not. `jumps_in_window` is how
        many jumps the store rejected for this ship in the spoofing window."""
        mmsi = event.mmsi
        if jumps_in_window == 0:
            self._spoofing.discard(mmsi)  # episode over: re-arm
            return []
        if jumps_in_window < self.cfg.spoof_jumps or mmsi in self._spoofing:
            return []
        self._spoofing.add(mmsi)
        track = self._latest.get(mmsi) or self._track_from(event)
        return [
            self._alerts.record(
                AlertKind.SPOOFING,
                track,
                event.received_at,
                f"{self._name(track)}: {jumps_in_window} impossible position jumps "
                f"in {self.cfg.spoof_window_min:g} min (spoofing or a duplicate MMSI?)",
            )
        ]

    def on_removed(self, track: Track) -> None:
        """Ship removed from the state. Keep its last position for gap checks."""
        mmsi = track.mmsi
        self._latest.pop(mmsi, None)
        self._loitering.discard(mmsi)
        self._spoofing.discard(mmsi)
        self._remove_from_grid(mmsi)
        for pair in [p for p in self._close_since if mmsi in p]:
            self._close_since.pop(pair, None)
            self._rdv_alerted.discard(pair)

    def on_tick(self, now: datetime) -> None:
        """Forget last-seen positions older than LAST_SEEN_MEMORY (bounded memory)."""
        cutoff = now - LAST_SEEN_MEMORY
        for mmsi in [m for m, t in self._last_seen.items() if t.last_seen < cutoff]:
            del self._last_seen[mmsi]

    # ---- detectors ----------------------------------------------------------

    def _check_reappeared(self, track: Track) -> list[Alert]:
        prev = self._last_seen.get(track.mmsi)
        if prev is None:
            return []
        gap = track.last_seen - prev.last_seen
        if gap < timedelta(minutes=self.cfg.gap_min_min):
            return []
        dist = haversine_nm(prev.latitude, prev.longitude, track.latitude, track.longitude)
        hours = gap.total_seconds() / 3600
        minutes = gap.total_seconds() / 60
        return [
            self._alerts.record(
                AlertKind.REAPPEARED,
                track,
                track.last_seen,
                f"{self._name(track)} reappeared after {minutes:.0f} min without AIS, "
                f"{dist:.1f} nm from where it vanished (implied {dist / hours:.1f} kn)",
            )
        ]

    def _check_loitering(self, track: Track, history: ShipHistory) -> list[Alert]:
        mmsi = track.mmsi
        window = timedelta(minutes=self.cfg.loiter_window_min)
        pts = history.recent(track.last_seen - window)
        loitering = False
        travel = radius = 0.0
        # The history must actually cover the window (allow 10% slack), or a
        # ship we just started seeing would look like it hasn't gone far.
        if len(pts) >= 3 and pts[-1][2] - pts[0][2] >= window * 0.9:
            travel = sum(
                haversine_nm(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:], strict=False)
            )
            c_lat = sum(p[0] for p in pts) / len(pts)
            c_lon = sum(p[1] for p in pts) / len(pts)
            radius = max(haversine_nm(c_lat, c_lon, p[0], p[1]) for p in pts)
            loitering = (
                travel >= self.cfg.loiter_min_travel_nm
                and radius <= self.cfg.loiter_max_radius_nm
                and not self._in_port(c_lat, c_lon)
            )
        if not loitering:
            self._loitering.discard(mmsi)
            return []
        if mmsi in self._loitering:
            return []
        self._loitering.add(mmsi)
        minutes = (pts[-1][2] - pts[0][2]).total_seconds() / 60
        return [
            self._alerts.record(
                AlertKind.LOITERING,
                track,
                track.last_seen,
                f"{self._name(track)} loitering: moved {travel:.1f} nm in {minutes:.0f} min "
                f"but stayed within {radius:.2f} nm",
            )
        ]

    def _check_rendezvous(self, track: Track) -> list[Alert]:
        cfg = self.cfg
        a = track.mmsi
        out: list[Alert] = []
        close_now: set[int] = set()
        if (
            track.sog < cfg.rendezvous_max_speed_kn
            and track.navigational_status != MOORED
            and not self._in_port(track.latitude, track.longitude)
        ):
            for b in self.neighbours(a):
                other = self._latest[b]
                if (
                    track.last_seen - other.last_seen <= PARTNER_MAX_AGE
                    and other.sog < cfg.rendezvous_max_speed_kn
                    and other.navigational_status != MOORED
                    and haversine_nm(
                        track.latitude, track.longitude, other.latitude, other.longitude
                    )
                    < cfg.rendezvous_max_distance_nm
                ):
                    close_now.add(b)

        # Pairs involving `a` that are no longer close: episode over, re-arm.
        for pair in [p for p in self._close_since if a in p]:
            if (pair[1] if pair[0] == a else pair[0]) not in close_now:
                self._close_since.pop(pair)
                self._rdv_alerted.discard(pair)

        for b in close_now:
            pair = (min(a, b), max(a, b))
            since = self._close_since.setdefault(pair, track.last_seen)
            duration = track.last_seen - since
            if pair in self._rdv_alerted or duration < timedelta(
                minutes=cfg.rendezvous_min_duration_min
            ):
                continue
            self._rdv_alerted.add(pair)
            other = self._latest[b]
            dist = haversine_nm(track.latitude, track.longitude, other.latitude, other.longitude)
            out.append(
                self._alerts.record(
                    AlertKind.RENDEZVOUS,
                    track,
                    track.last_seen,
                    f"{self._name(track)} and {self._name(other)} within {dist:.2f} nm, "
                    f"both under {cfg.rendezvous_max_speed_kn:g} kn, "
                    f"for {duration.total_seconds() / 60:.0f} min (possible transfer)",
                    other_mmsi=b,
                )
            )
        return out

    # ---- spatial grid -------------------------------------------------------

    def neighbours(self, mmsi: int) -> set[int]:
        """Ships in the same or adjacent grid cells (candidates, not filtered by
        distance). With cells >= the rendezvous distance, no close pair is missed."""
        lat_c, lon_c = self._cell[mmsi]
        found: set[int] = set()
        for dlat in (-1, 0, 1):
            for dlon in (-1, 0, 1):
                found |= self._grid.get((lat_c + dlat, lon_c + dlon), set())
        found.discard(mmsi)
        return found

    def _move_in_grid(self, track: Track) -> None:
        new = cell_of(track.latitude, track.longitude)
        if self._cell.get(track.mmsi) == new:
            return
        self._remove_from_grid(track.mmsi)
        self._cell[track.mmsi] = new
        self._grid.setdefault(new, set()).add(track.mmsi)

    def _remove_from_grid(self, mmsi: int) -> None:
        old = self._cell.pop(mmsi, None)
        if old is not None:
            members = self._grid[old]
            members.discard(mmsi)
            if not members:
                del self._grid[old]

    # ---- helpers ------------------------------------------------------------

    def _in_port(self, lat: float, lon: float) -> bool:
        return any(z.near(lat, lon, PORT_MARGIN_NM) for z in self._ports)

    @staticmethod
    def _name(track: Track) -> str:
        return track.ship_name or str(track.mmsi)

    @staticmethod
    def _track_from(event: PositionEvent) -> Track:
        """A ship whose every position was rejected has no Track yet."""
        return Track(
            mmsi=event.mmsi,
            ship_name=event.ship_name,
            latitude=event.latitude,
            longitude=event.longitude,
            sog=event.sog,
            cog=event.cog,
            true_heading=event.true_heading,
            navigational_status=event.navigational_status,
            last_seen=event.received_at,
            ais_class=event.ais_class,  # a Class B craft was shown as Class A (review)
        )
