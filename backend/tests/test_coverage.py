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


def test_restored_gaps_are_forgotten_after_memory():
    mon = monitor()
    ships = cluster(4, timedelta(seconds=20))
    run_sweeps(mon, ships)
    for t in ships[:2]:  # half back: restored
        mon.on_track(t.model_copy(update={"last_seen": STALE_AT + timedelta(minutes=5)}))
    mon.on_tick(STALE_AT + timedelta(hours=CFG.gap_memory_h, minutes=10))
    _, in_gap = mon.on_track(ships[3].model_copy(update={"last_seen": T0 + timedelta(hours=3)}))
    assert in_gap is False


def test_long_outage_is_still_one_gap_when_ships_return():
    """Review fix: an unrestored gap is not forgotten at gap_memory_h, so a
    3 h outage ends with "coverage restored", not one "reappeared" per ship."""
    mon = monitor()
    ships = cluster(4, timedelta(seconds=20))
    run_sweeps(mon, ships)
    back = STALE_AT + timedelta(hours=3)
    mon.on_tick(back)
    results = [mon.on_track(t.model_copy(update={"last_seen": back})) for t in ships]
    assert all(in_gap for _, in_gap in results)
    kinds = [a.kind for alerts, _ in results for a in alerts]
    assert kinds == ["coverage_restored"]


def test_open_gap_does_not_keep_absorbing_a_chain_of_ships():
    """Review fix: the join window is fixed when the gap opens. Before, each
    ship that joined pushed the window forward, so ships going silent one by
    one, each within max_spread_s of the previous, all disappeared into the gap."""
    mon = monitor()
    run_sweeps(mon, cluster(4, timedelta(seconds=20)))  # cohort silent T0..T0+20 s
    chain = [
        track(50, TAGUS[0] + 0.01, TAGUS[1], T0 + timedelta(seconds=120)),  # within the window
        track(51, TAGUS[0] + 0.02, TAGUS[1], T0 + timedelta(seconds=220)),  # only via the chain
    ]
    released = []
    for t in chain:
        stale_at = t.last_seen + timedelta(minutes=10)
        mon.add_stale(t, stale_at)
        _, r = mon.process(stale_at + timedelta(seconds=CFG.max_spread_s))
        released += [x.mmsi for x in r]
    assert released == [51]  # 50 joined the gap; 51 is judged on its own


def test_a_returned_ship_is_not_in_the_gap_any_more():
    """Review fix: in_gap only on a ship's first return; a later silence of
    its own must not have its 'reappeared' suppressed."""
    mon = monitor()
    ships = cluster(4, timedelta(seconds=20))
    run_sweeps(mon, ships)
    first = ships[0].model_copy(update={"last_seen": STALE_AT + timedelta(minutes=5)})
    assert mon.on_track(first)[1] is True
    again = ships[0].model_copy(update={"last_seen": STALE_AT + timedelta(minutes=50)})
    assert mon.on_track(again)[1] is False


def test_second_gap_with_the_same_ships_is_restored_too():
    """Review fix: a ship in two gaps (same receiver fails twice) counts as
    returned in both."""
    mon = monitor()
    ships = cluster(4, timedelta(seconds=20))
    run_sweeps(mon, ships)
    back = STALE_AT + timedelta(minutes=5)
    for t in ships:
        mon.on_track(t.model_copy(update={"last_seen": back}))  # gap 1 restored
    # Silent again together 40 min later: a second gap with the same ships.
    later = [t.model_copy(update={"last_seen": t.last_seen + timedelta(minutes=40)}) for t in ships]
    alerts2 = []
    for k in range(10):
        now = STALE_AT + timedelta(minutes=40, seconds=30 * k)
        for t in later:
            stale_at = t.last_seen + timedelta(minutes=10)
            if now - timedelta(seconds=30) < stale_at <= now:
                mon.add_stale(t, now)
        a, _ = mon.process(now)
        alerts2 += a
    assert [a.kind for a in alerts2] == ["coverage_lost"]
    back2 = STALE_AT + timedelta(minutes=55)
    kinds = [
        a.kind for t in later for a in mon.on_track(t.model_copy(update={"last_seen": back2}))[0]
    ]
    assert kinds == ["coverage_restored"]
