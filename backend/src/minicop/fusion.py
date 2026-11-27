"""AIS + sensor fusion: which detections are explained by AIS, which are not.

Pure logic, run by the state task once per sensor sweep. The steps, all
deliberately simple and explainable (the baseline a Kalman/JPDA tracker would
be compared against):

1. Predict every recent AIS track to the sweep time (dead reckoning).
2. Gate: a detection can only match a track within a radius that grows with
   the time since that track's last AIS report.
3. Assign: greedy global nearest neighbour - all (detection, track) pairs inside
   their gates, closest first; each detection and each track used at most once.
4. Unmatched detections feed candidate non-cooperative tracks. A candidate is
   confirmed as a DARK track after M detections in the last N sweeps, with
   physically plausible speed between them. Isolated clutter never confirms.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pydantic import BaseModel

from minicop.events import Track
from minicop.geo import haversine_nm
from minicop.sensors import Detection, FusionConfig, Sweep

# Speed and course are only reported once a contact's detections span this long.
MIN_SPAN_FOR_SPEED = timedelta(minutes=3)


def dead_reckon(track: Track, t: datetime) -> tuple[float, float]:
    """Where the ship would be at `t`, keeping its last speed and course.
    COG 360 means "not available": then assume it stayed put."""
    hours = (t - track.last_seen).total_seconds() / 3600
    if track.cog >= 360 or track.sog <= 0 or hours <= 0:
        return track.latitude, track.longitude
    dist_nm = track.sog * hours
    north = dist_nm * math.cos(math.radians(track.cog))
    east = dist_nm * math.sin(math.radians(track.cog))
    return (
        track.latitude + north / 60,
        track.longitude + east / (60 * math.cos(math.radians(track.latitude))),
    )


def gate_nm(cfg: FusionConfig, age: timedelta) -> float:
    minutes = max(0.0, age.total_seconds() / 60)
    return min(cfg.gate_max_nm, cfg.gate_nm + cfg.gate_growth_nm_per_min * minutes)


def associate(
    detections: list[Detection], tracks: list[Track], t: datetime, cfg: FusionConfig
) -> tuple[dict[int, int], list[int]]:
    """Greedy global nearest neighbour. Returns ({detection index: mmsi},
    [indexes of unassociated detections])."""
    max_age = timedelta(minutes=cfg.track_max_age_min)
    usable = [tr for tr in tracks if timedelta(0) <= t - tr.last_seen <= max_age]
    pairs: list[tuple[float, int, int]] = []
    for i, det in enumerate(detections):
        for tr in usable:
            plat, plon = dead_reckon(tr, t)
            d = haversine_nm(det.lat, det.lon, plat, plon)
            if d <= gate_nm(cfg, t - tr.last_seen):
                pairs.append((d, i, tr.mmsi))
    pairs.sort()
    matched: dict[int, int] = {}
    used_tracks: set[int] = set()
    for _, i, mmsi in pairs:
        if i not in matched and mmsi not in used_tracks:
            matched[i] = mmsi
            used_tracks.add(mmsi)
    unmatched = [i for i in range(len(detections)) if i not in matched]
    return matched, unmatched


class DarkTrack(BaseModel):
    """A contact seen by the sensor that no AIS track explains."""

    id: str
    lat: float
    lon: float
    # Estimated from its detections; None until they span MIN_SPAN_FOR_SPEED,
    # because with ~150 m position error, 3 detections in 1 minute gave 16 kn
    # for a 6 kn target (seen in the browser test).
    sog: float | None
    cog: float | None
    detections: int
    first_seen: datetime
    last_seen: datetime
    confirmed: bool
    source: str = "sensor"  # vs "ais" / "ais+sensor" for AIS tracks


@dataclass
class _Candidate:
    id: str
    points: list[Detection] = field(default_factory=list)
    hit_sweeps: list[int] = field(default_factory=list)  # sweep numbers with a hit
    confirmed: bool = False

    @property
    def last(self) -> Detection:
        return self.points[-1]

    def velocity(self) -> tuple[float, float] | None:
        """(sog kn, cog deg) from first to last detection, or None if they span
        less than MIN_SPAN_FOR_SPEED (too noisy to be worth showing)."""
        a, b = self.points[0], self.points[-1]
        if b.time - a.time < MIN_SPAN_FOR_SPEED:
            return None
        hours = (b.time - a.time).total_seconds() / 3600
        dist = haversine_nm(a.lat, a.lon, b.lat, b.lon)
        north = (b.lat - a.lat) * 60
        east = (b.lon - a.lon) * 60 * math.cos(math.radians(a.lat))
        return dist / hours, (math.degrees(math.atan2(east, north)) + 360) % 360


@dataclass
class SweepOutcome:
    fused: dict[int, datetime]  # mmsi -> time confirmed by the sensor
    newly_confirmed: list[DarkTrack]
    dark: list[DarkTrack]  # all current confirmed dark tracks


class FusionEngine:
    def __init__(self, cfg: FusionConfig) -> None:
        self.cfg = cfg
        self._candidates: list[_Candidate] = []
        self._sweep_no = 0
        self._next_id = 1

    def process(self, sweep: Sweep, tracks: list[Track]) -> SweepOutcome:
        self._sweep_no += 1
        t = sweep.time
        matched, unmatched = associate(sweep.detections, tracks, t, self.cfg)
        fused = {mmsi: t for mmsi in matched.values()}

        newly: list[_Candidate] = []
        for i in unmatched:
            det = sweep.detections[i]
            cand = self._nearest_candidate(det)
            if cand is None:
                cand = _Candidate(id=f"D-{self._next_id}")
                self._next_id += 1
                self._candidates.append(cand)
            cand.points.append(det)
            if not cand.hit_sweeps or cand.hit_sweeps[-1] != self._sweep_no:
                cand.hit_sweeps.append(self._sweep_no)
            if not cand.confirmed and self._should_confirm(cand):
                cand.confirmed = True
                newly.append(cand)

        # Forget candidates and dark tracks not seen for a while.
        drop = timedelta(minutes=self.cfg.drop_after_min)
        self._candidates = [c for c in self._candidates if t - c.last.time <= drop]
        dark = [self._as_dark(c) for c in self._candidates if c.confirmed]
        return SweepOutcome(
            fused=fused, newly_confirmed=[self._as_dark(c) for c in newly], dark=dark
        )

    def _nearest_candidate(self, det: Detection) -> _Candidate | None:
        best: tuple[float, _Candidate] | None = None
        for c in self._candidates:
            # Only candidates still inside the confirmation window can take new
            # detections. Old hits never count towards confirmation anyway (M of
            # the last N sweeps); this keeps a stale candidate, whose reachable
            # radius (max speed x time) keeps growing, from taking a detection
            # that belongs to a new contact and skewing its speed estimate.
            # Measured: it does not change the clutter false-confirmation rate.
            if not c.confirmed and self._sweep_no - c.hit_sweeps[-1] >= self.cfg.confirm_window:
                continue
            last = c.last
            hours = (det.time - last.time).total_seconds() / 3600
            if hours <= 0:
                continue  # one detection per candidate per sweep
            d = haversine_nm(det.lat, det.lon, last.lat, last.lon)
            # Within the gate, or reachable at a plausible speed (a moving
            # target seen a few sweeps ago can be further than the gate).
            if d > max(self.cfg.candidate_gate_nm, self.cfg.max_speed_kn * hours):
                continue
            if best is None or d < best[0]:
                best = (d, c)
        return best[1] if best else None

    def _should_confirm(self, c: _Candidate) -> bool:
        window_start = self._sweep_no - self.cfg.confirm_window + 1
        hits = [s for s in c.hit_sweeps if s >= window_start]
        if len(hits) < self.cfg.confirm_hits:
            return False
        # Plausibility: no hop between consecutive detections faster than a ship.
        for p, q in zip(c.points, c.points[1:], strict=False):
            hours = (q.time - p.time).total_seconds() / 3600
            if (
                hours > 0
                and haversine_nm(p.lat, p.lon, q.lat, q.lon) / hours > self.cfg.max_speed_kn
            ):
                return False
        return True

    def _as_dark(self, c: _Candidate) -> DarkTrack:
        v = c.velocity()
        sog, cog = v if v else (None, None)
        return DarkTrack(
            id=c.id,
            lat=c.last.lat,
            lon=c.last.lon,
            sog=sog,
            cog=cog,
            detections=len(c.points),
            first_seen=c.points[0].time,
            last_seen=c.last.time,
            confirmed=c.confirmed,
        )
