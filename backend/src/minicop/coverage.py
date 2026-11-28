"""Coverage gaps: telling "we lost reception" apart from "a ship went dark".

Independent ships don't fall silent within the same couple of minutes; a
receiver (or the feed's coverage of an area) does. When enough ships in one
region go stale with their last reports close together, that is a coverage
gap: one alert for the gap, and no per-ship "dark" / "reappeared" alerts.

Pure logic, run by the state task (the single writer).

Timing: ships that fell silent within `max_spread_s` of each other become
stale in sweeps up to that far apart. So a newly stale ship is held as
*pending* for `max_spread_s` before its "dark" alert is released, giving the
rest of its cohort time to arrive. That delays genuine "dark" alerts by about
two minutes, which is small next to the 10 min it takes to call a ship stale.
"""

import math
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from minicop.alerts import Alert, AlertEngine, AlertKind
from minicop.anomalies import DEFAULT_ANOMALIES_FILE
from minicop.events import Track

Region = tuple[int, int]

# An unrestored gap is kept this long even past gap_memory_h: forgetting it at
# 2 h turned a long outage back into one "reappeared" alert per ship, with no
# "coverage restored" (found in review). Restored gaps go after gap_memory_h.
MAX_OPEN_GAP = timedelta(hours=24)


class CoverageConfig(BaseModel):
    min_ships: int
    max_spread_s: float
    region_deg: float
    gap_memory_h: float


def load_coverage_config(path: Path = DEFAULT_ANOMALIES_FILE) -> CoverageConfig:
    with path.open("rb") as f:
        return CoverageConfig(**tomllib.load(f)["coverage"])


@dataclass
class _Pending:
    track: Track
    since: datetime  # when it became stale (sweep time)


@dataclass
class CoverageGap:
    region: Region
    ships: dict[int, Track]  # last known track of each ship in the gap
    first_silent: datetime
    last_silent: datetime
    opened_at: datetime
    # Ships can join only while silent no later than this: the opening cohort's
    # last report + spread. Fixed at opening; it used to slide with every ship
    # that joined, so an open gap kept absorbing ships (hiding real "dark" ones).
    join_until: datetime
    returned: set[int] = field(default_factory=set)
    restored: bool = False


class CoverageMonitor:
    def __init__(self, config: CoverageConfig, alerts: AlertEngine) -> None:
        self.cfg = config
        self._alerts = alerts
        self._pending: dict[int, _Pending] = {}
        self._gaps: list[CoverageGap] = []

    # ---- entry points ---------------------------------------------------------

    def add_stale(self, track: Track, now: datetime) -> None:
        """A ship just became stale. Its fate (gap member or 'dark') is decided
        in process() once its cohort has had time to arrive."""
        self._pending[track.mmsi] = _Pending(track, now)

    def process(self, now: datetime) -> tuple[list[Alert], list[Track]]:
        """Open or extend gaps from pending ships. Returns the coverage alerts
        raised, and the ships whose 'dark' alert should be evaluated now
        (pending long enough, not part of any gap)."""
        alerts: list[Alert] = []
        spread = timedelta(seconds=self.cfg.max_spread_s)

        # 1. Pending ships that fit an open gap in their region join it.
        for mmsi, p in list(self._pending.items()):
            gap = self._open_gap_for(p.track, spread)
            if gap is not None:
                self._join(gap, p.track)
                del self._pending[mmsi]

        # 2. New gaps: per region, the largest set of pending ships whose last
        #    reports fit within `spread` (sliding window over sorted times).
        by_region: dict[Region, list[Track]] = {}
        for p in self._pending.values():
            by_region.setdefault(self.region_of(p.track), []).append(p.track)
        for region, tracks in by_region.items():
            cohort = self._largest_cohort(tracks, spread)
            if len(cohort) < self.cfg.min_ships:
                continue
            gap = CoverageGap(
                region=region,
                ships={t.mmsi: t for t in cohort},
                first_silent=min(t.last_seen for t in cohort),
                last_silent=max(t.last_seen for t in cohort),
                opened_at=now,
                join_until=max(t.last_seen for t in cohort) + spread,
            )
            self._gaps.append(gap)
            for t in cohort:
                del self._pending[t.mmsi]
            alerts.append(self._lost_alert(gap))

        # 3. Release ships that waited long enough without joining a gap.
        released = [p.track for p in self._pending.values() if now - p.since >= spread]
        for t in released:
            del self._pending[t.mmsi]
        return alerts, released

    def on_track(self, track: Track) -> tuple[list[Alert], bool]:
        """A ship reported. Returns (alerts, in_gap): in_gap means its silence
        was a coverage gap, so a 'reappeared' alert must be suppressed."""
        self._pending.pop(track.mmsi, None)  # came back before being judged
        alerts: list[Alert] = []
        in_gap = False
        # Every gap the ship belongs to (the same receiver can fail twice), but
        # only on its FIRST return to each: once back, a later silence of its
        # own is its own (found in review: in_gap stayed true for 2 h).
        for gap in self._gaps:
            if track.mmsi not in gap.ships or track.mmsi in gap.returned:
                continue
            in_gap = True
            gap.returned.add(track.mmsi)
            if not gap.restored and len(gap.returned) * 2 >= len(gap.ships):
                gap.restored = True
                alerts.append(self._restored_alert(gap, track))
        return alerts, in_gap

    def on_tick(self, now: datetime) -> None:
        """Forget restored gaps older than gap_memory_h, and unrestored ones
        older than MAX_OPEN_GAP (bounded memory)."""
        memory = timedelta(hours=self.cfg.gap_memory_h)
        self._gaps = [
            g for g in self._gaps if now - g.opened_at < (memory if g.restored else MAX_OPEN_GAP)
        ]

    # ---- helpers --------------------------------------------------------------

    def region_of(self, track: Track) -> Region:
        d = self.cfg.region_deg
        return math.floor(track.latitude / d), math.floor(track.longitude / d)

    @staticmethod
    def _largest_cohort(tracks: list[Track], spread: timedelta) -> list[Track]:
        ordered = sorted(tracks, key=lambda t: t.last_seen)
        best: list[Track] = []
        start = 0
        for end, t in enumerate(ordered):
            while t.last_seen - ordered[start].last_seen > spread:
                start += 1
            if end - start + 1 > len(best):
                best = ordered[start : end + 1]
        return best

    def _open_gap_for(self, track: Track, spread: timedelta) -> CoverageGap | None:
        for gap in self._gaps:
            if (
                not gap.restored
                and gap.region == self.region_of(track)
                and gap.first_silent - spread <= track.last_seen <= gap.join_until
            ):
                return gap
        return None

    @staticmethod
    def _join(gap: CoverageGap, track: Track) -> None:
        gap.ships[track.mmsi] = track
        gap.first_silent = min(gap.first_silent, track.last_seen)
        gap.last_silent = max(gap.last_silent, track.last_seen)

    @staticmethod
    def _centroid(gap: CoverageGap) -> tuple[float, float]:
        ships = list(gap.ships.values())
        return (
            sum(t.latitude for t in ships) / len(ships),
            sum(t.longitude for t in ships) / len(ships),
        )

    @staticmethod
    def _where(lat: float, lon: float) -> str:
        return f"{abs(lat):.1f}{'N' if lat >= 0 else 'S'} {abs(lon):.1f}{'E' if lon >= 0 else 'W'}"

    def _lost_alert(self, gap: CoverageGap) -> Alert:
        lat, lon = self._centroid(gap)
        ships = sorted(gap.ships.values(), key=lambda t: t.last_seen)
        names = [t.ship_name or str(t.mmsi) for t in ships]
        listed = ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")
        spread_s = (gap.last_silent - gap.first_silent).total_seconds()
        # The alert is attached to the first ship that went silent, so the
        # map can fly there; the message carries the whole cohort.
        return self._alerts.record(
            AlertKind.COVERAGE_LOST,
            ships[0],
            gap.opened_at,
            f"Coverage lost near {self._where(lat, lon)}: {len(ships)} ships went silent "
            f"within {spread_s:.0f} s ({listed})",
        )

    def _restored_alert(self, gap: CoverageGap, track: Track) -> Alert:
        lat, lon = self._centroid(gap)
        minutes = (track.last_seen - gap.last_silent).total_seconds() / 60
        return self._alerts.record(
            AlertKind.COVERAGE_RESTORED,
            track,
            track.last_seen,
            f"Coverage restored near {self._where(lat, lon)} after {minutes:.0f} min "
            f"({len(gap.returned)} of {len(gap.ships)} ships back)",
        )
