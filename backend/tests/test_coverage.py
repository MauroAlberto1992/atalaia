"""Coverage gaps vs ships going dark, on plausible synthetic data."""

from datetime import UTC, datetime, timedelta

from minicop.alerts import AlertEngine, AlertKind
from minicop.coverage import CoverageMonitor, load_coverage_config
from minicop.events import Track

T0 = datetime(2026, 11, 25, 8, 9, 0, tzinfo=UTC)  # when the ships fell silent
STALE_AT = T0 + timedelta(minutes=10)  # first sweep that sees them stale
CFG = load_coverage_config()
TAGUS = (38.68, -9.33)


def track(mmsi: int, lat: float, lon: float, last_seen: datetime) -> Track:
    return Track(
        mmsi=mmsi,
        ship_name=f"SHIP{mmsi}",
        latitude=lat,
        longitude=lon,
        sog=8,
        cog=0,
        true_heading=511,
        navigational_status=0,
        last_seen=last_seen,
    )


def monitor() -> CoverageMonitor:
    return CoverageMonitor(CFG, AlertEngine([]))


def cluster(n: int, spread: timedelta, where=TAGUS, first_mmsi: int = 1) -> list[Track]:
    """n ships a few hundred metres apart whose last reports span `spread`."""
    step = spread / max(n - 1, 1)
    return [track(first_mmsi + i, where[0] + 0.005 * i, where[1], T0 + step * i) for i in range(n)]


def run_sweeps(mon: CoverageMonitor, tracks: list[Track], minutes: int = 5):
    """Feed tracks as the 30 s sweeps would (each becomes stale 10 min after its
    last report) and collect what the monitor decides."""
    alerts, released = [], []
    for k in range(minutes * 2):
        now = STALE_AT + timedelta(seconds=30 * k)
        for t in tracks:
            becomes_stale = t.last_seen + timedelta(minutes=10)
            if now - timedelta(seconds=30) < becomes_stale <= now:
                mon.add_stale(t, now)
        a, r = mon.process(now)
        alerts += a
        released += r
    return alerts, released


def test_many_ships_silent_together_is_one_coverage_gap():
    alerts, released = run_sweeps(monitor(), cluster(5, timedelta(seconds=30)))
    assert [a.kind for a in alerts] == [AlertKind.COVERAGE_LOST]
    assert "5 ships went silent within 30 s" in alerts[0].message
    assert released == []  # no per-ship "dark" evaluation


def test_cohort_split_across_sweeps_is_still_one_gap():
    # 100 s spread: the ships become stale in up to 4 different sweeps.
    alerts, released = run_sweeps(monitor(), cluster(6, timedelta(seconds=100)))
    assert [a.kind for a in alerts] == [AlertKind.COVERAGE_LOST]
    assert released == []


def test_lone_ship_is_released_for_dark():
    lone = [track(1, *TAGUS, T0)]
    alerts, released = run_sweeps(monitor(), lone)
    assert alerts == []
    assert [t.mmsi for t in released] == [1]


def test_ships_silent_over_ten_minutes_are_individual():
    alerts, released = run_sweeps(monitor(), cluster(5, timedelta(minutes=10)), minutes=15)
    assert alerts == []
    assert len(released) == 5


def test_same_moment_but_different_regions_is_not_a_gap():
    far_apart = [track(i, 37.0 + i * 1.0, -9.0, T0) for i in range(5)]  # 60 nm apart
    alerts, released = run_sweeps(monitor(), far_apart)
    assert alerts == []
    assert len(released) == 5


def test_return_after_gap_suppresses_reappeared_and_restores_once():
    mon = monitor()
    ships = cluster(4, timedelta(seconds=20))
    run_sweeps(mon, ships)
    back = T0 + timedelta(minutes=40)
    results = [mon.on_track(t.model_copy(update={"last_seen": back})) for t in ships]
    assert all(in_gap for _, in_gap in results)  # "reappeared" suppressed for all
    kinds = [a.kind for alerts, _ in results for a in alerts]
    assert kinds == [AlertKind.COVERAGE_RESTORED]  # once, when half are back
    restored = next(a for alerts, _ in results for a in alerts)
    assert "after 40 min" in restored.message


def test_ship_outside_any_gap_is_not_suppressed():
    alerts, in_gap = monitor().on_track(track(99, *TAGUS, T0))
    assert alerts == [] and in_gap is False


def test_gaps_are_forgotten_after_memory():
    mon = monitor()
    ships = cluster(4, timedelta(seconds=20))
    run_sweeps(mon, ships)
    mon.on_tick(STALE_AT + timedelta(hours=CFG.gap_memory_h, minutes=10))
    _, in_gap = mon.on_track(ships[0].model_copy(update={"last_seen": T0 + timedelta(hours=3)}))
    assert in_gap is False
