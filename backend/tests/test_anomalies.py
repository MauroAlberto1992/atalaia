"""Anomaly detectors on synthetic, physically plausible tracks."""

import math
import random
from datetime import UTC, datetime, timedelta

import pytest

from minicop.alerts import AlertEngine, AlertKind
from minicop.anomalies import AnomalyDetector, load_anomaly_config
from minicop.events import PositionEvent, Track
from minicop.geo import haversine_nm
from minicop.history import ShipHistory
from minicop.state import TrackStore
from minicop.zones import Zone

T0 = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
CFG = load_anomaly_config()  # the real thresholds from config/anomalies.toml
OFFSHORE = (36.85, -8.40)  # open sea south of the Algarve
PORT_CENTRE = (37.125, -8.53)
PORT = Zone(
    name="Port (test)",
    kind="port",
    polygon=[(37.10, -8.55), (37.15, -8.55), (37.15, -8.51), (37.10, -8.51)],
)


def detector() -> AnomalyDetector:
    return AnomalyDetector(CFG, [PORT], AlertEngine([PORT]))


def track(mmsi: int, lat: float, lon: float, t: datetime, sog: float = 3.0) -> Track:
    return Track(
        mmsi=mmsi,
        ship_name=f"SHIP{mmsi}",
        latitude=lat,
        longitude=lon,
        sog=sog,
        cog=0,
        true_heading=511,
        navigational_status=0,
        last_seen=t,
    )


def offset(lat: float, lon: float, north_nm: float, east_nm: float) -> tuple[float, float]:
    return lat + north_nm / 60, lon + east_nm / (60 * math.cos(math.radians(lat)))


def kinds(alerts) -> list[AlertKind]:
    return [a.kind for a in alerts]


# ---- loitering ---------------------------------------------------------------


def circle(det: AnomalyDetector, centre, minutes: int, speed_kn=5.0, radius_nm=0.2, mmsi=1):
    """Circle at constant speed, one report per minute. Returns all alerts.
    5 kn, not 4: at 4 kn the 30 min of chords sum to 1.99 nm, just under the
    2 nm threshold (a chord is shorter than its arc). Keep test data off the edge."""
    history, alerts = ShipHistory(), []
    for m in range(minutes + 1):
        angle = speed_kn * m / 60 / radius_nm  # radians travelled
        lat, lon = offset(*centre, radius_nm * math.sin(angle), radius_nm * math.cos(angle))
        t = T0 + timedelta(minutes=m)
        history.add(lat, lon, t)
        alerts += det.on_track(track(mmsi, lat, lon, t, sog=speed_kn), history)
    return alerts


def test_circling_offshore_is_loitering_once():
    alerts = circle(detector(), OFFSHORE, minutes=45)
    assert kinds(alerts) == [AlertKind.LOITERING]  # fires once per episode
    assert "stayed within" in alerts[0].message


def test_circling_in_port_is_not_loitering():
    assert circle(detector(), PORT_CENTRE, minutes=45) == []


def test_too_short_history_is_not_loitering():
    assert circle(detector(), OFFSHORE, minutes=20) == []  # window not covered yet


def test_anchored_ship_is_not_loitering():
    det, history, alerts = detector(), ShipHistory(), []
    for m in range(45):  # GPS noise of a few metres: jitter, not travel
        lat, lon = offset(*OFFSHORE, 0.001 * (m % 3), 0.0)
        t = T0 + timedelta(minutes=m)
        history.add(lat, lon, t)
        alerts += det.on_track(track(1, lat, lon, t, sog=0.1), history)
    assert alerts == []


def test_transiting_ship_is_not_loitering():
    det, history, alerts = detector(), ShipHistory(), []
    for m in range(45):  # straight line at 10 kn
        lat, lon = offset(*OFFSHORE, 0.0, 10 * m / 60)
        t = T0 + timedelta(minutes=m)
        history.add(lat, lon, t)
        alerts += det.on_track(track(1, lat, lon, t, sog=10), history)
    assert alerts == []


# ---- rendezvous ----------------------------------------------------------------


def side_by_side(det: AnomalyDetector, minutes: int, where=OFFSHORE, sog_b=0.5):
    """Two ships 0.1 nm apart, both reporting every minute."""
    alerts = []
    b_pos = offset(*where, 0.0, 0.1)
    for m in range(minutes + 1):
        t = T0 + timedelta(minutes=m)
        alerts += det.on_track(track(1, *where, t, sog=0.5), None)
        alerts += det.on_track(track(2, *b_pos, t + timedelta(seconds=5), sog=sog_b), None)
    return alerts


def test_rendezvous_after_ten_minutes_once():
    alerts = side_by_side(detector(), minutes=15)
    assert kinds(alerts) == [AlertKind.RENDEZVOUS]
    assert {alerts[0].mmsi, alerts[0].other_mmsi} == {1, 2}


def test_short_meeting_is_not_rendezvous():
    assert side_by_side(detector(), minutes=5) == []


def test_fast_ship_passing_is_not_rendezvous():
    assert side_by_side(detector(), minutes=15, sog_b=10) == []


def test_ships_moored_together_in_port_are_not_rendezvous():
    assert side_by_side(detector(), minutes=15, where=PORT_CENTRE) == []


def test_rendezvous_rearms_after_ships_separate():
    det = detector()
    assert len(side_by_side(det, minutes=15)) == 1
    det.on_track(track(2, *offset(*OFFSHORE, 0.0, 2.0), T0 + timedelta(minutes=20)), None)
    det.on_track(track(1, *OFFSHORE, T0 + timedelta(minutes=20, seconds=10), sog=0.5), None)
    # Meet again later: a new episode.
    alerts = []
    b_pos = offset(*OFFSHORE, 0.0, 0.1)
    for m in range(30, 45):
        t = T0 + timedelta(minutes=m)
        alerts += det.on_track(track(1, *OFFSHORE, t, sog=0.5), None)
        alerts += det.on_track(track(2, *b_pos, t + timedelta(seconds=5), sog=0.5), None)
    assert kinds(alerts) == [AlertKind.RENDEZVOUS]


def test_grid_finds_the_same_close_pairs_as_brute_force():
    rng = random.Random(7)
    det = detector()
    ships = {}
    for mmsi in range(300):  # dense cluster: ~5 x 5 nm
        lat, lon = OFFSHORE[0] + rng.uniform(0, 0.08), OFFSHORE[1] + rng.uniform(0, 0.1)
        ships[mmsi] = (lat, lon)
        det.on_track(track(mmsi, lat, lon, T0, sog=8), None)

    def close(a: int, b: int) -> bool:
        return haversine_nm(*ships[a], *ships[b]) < CFG.rendezvous_max_distance_nm

    for a in ships:
        via_grid = {b for b in det.neighbours(a) if close(a, b)}
        brute = {b for b in ships if b != a and close(a, b)}
        assert via_grid == brute


# ---- reappeared ---------------------------------------------------------------


def test_reappearance_after_long_gap():
    det = detector()
    det.on_track(track(1, *OFFSHORE, T0), None)
    later = offset(*OFFSHORE, 5.0, 0.0)  # 5 nm north
    alerts = det.on_track(track(1, *later, T0 + timedelta(minutes=45)), None)
    assert kinds(alerts) == [AlertKind.REAPPEARED]
    assert "45 min" in alerts[0].message
    assert "5.0 nm" in alerts[0].message
    assert "6.7 kn" in alerts[0].message  # 5 nm / 0.75 h


def test_short_gap_is_not_reappearance():
    det = detector()
    det.on_track(track(1, *OFFSHORE, T0), None)
    assert det.on_track(track(1, *OFFSHORE, T0 + timedelta(minutes=15)), None) == []


def test_reappearance_after_removal_from_state():
    det = detector()
    first = track(1, *OFFSHORE, T0)
    det.on_track(first, None)
    det.on_removed(first)  # the store forgets ships after 60 min
    alerts = det.on_track(track(1, *OFFSHORE, T0 + timedelta(hours=3)), None)
    assert kinds(alerts) == [AlertKind.REAPPEARED]


def test_last_seen_memory_is_bounded():
    det = detector()
    det.on_track(track(1, *OFFSHORE, T0), None)
    det.on_tick(T0 + timedelta(hours=25))
    assert det.on_track(track(1, *OFFSHORE, T0 + timedelta(hours=26)), None) == []


# ---- spoofing -----------------------------------------------------------------


def event(lat: float, t: datetime, mmsi: int = 1) -> PositionEvent:
    return PositionEvent(
        mmsi=mmsi,
        latitude=lat,
        longitude=-8.4,
        sog=8,
        cog=0,
        true_heading=511,
        navigational_status=0,
        ship_name="SHIP1",
        received_at=t,
    )


def test_spoofing_threshold_and_episode():
    det = detector()
    e = event(36.85, T0)
    assert det.on_position(e, 2) == []
    assert kinds(det.on_position(e, 3)) == [AlertKind.SPOOFING]
    assert det.on_position(e, 4) == []  # same episode
    assert det.on_position(e, 0) == []  # episode over
    assert kinds(det.on_position(e, 3)) == [AlertKind.SPOOFING]


def test_two_transmitters_with_one_mmsi_through_the_store():
    """Alternating reports 60 nm apart, as with a duplicated MMSI."""
    store, det, alerts = TrackStore(), detector(), []
    window = timedelta(minutes=CFG.spoof_window_min)
    for i in range(10):
        t = T0 + timedelta(seconds=30 * i)
        e = event(36.85 if i % 2 == 0 else 37.85, t)
        tr = store.apply(e)
        if tr is not None:
            alerts += det.on_track(tr, store.history(1))
        alerts += det.on_position(e, store.jumps_since(1, t - window))
    assert kinds(alerts) == [AlertKind.SPOOFING]


@pytest.mark.parametrize("kind", ["enter", "loitering", "rendezvous", "reappeared", "spoofing"])
def test_alert_kinds_serialise(kind):
    assert AlertKind(kind).value == kind


def test_moored_ships_together_are_not_rendezvous():
    det, alerts = detector(), []
    b_pos = offset(*OFFSHORE, 0.0, 0.02)
    for m in range(16):
        t = T0 + timedelta(minutes=m)
        moored_a = track(1, *OFFSHORE, t, sog=0.0).model_copy(update={"navigational_status": 5})
        alerts += det.on_track(moored_a, None)
        alerts += det.on_track(track(2, *b_pos, t + timedelta(seconds=5), sog=0.0), None)
    assert alerts == []


def test_ships_at_anchor_together_still_count():
    det, alerts = detector(), []
    b_pos = offset(*OFFSHORE, 0.0, 0.05)
    for m in range(16):
        t = T0 + timedelta(minutes=m)
        a = track(1, *OFFSHORE, t, sog=0.0).model_copy(update={"navigational_status": 1})
        b = track(2, *b_pos, t + timedelta(seconds=5), sog=0.0)
        alerts += det.on_track(a, None)
        alerts += det.on_track(b.model_copy(update={"navigational_status": 1}), None)
    assert kinds(alerts) == [AlertKind.RENDEZVOUS]


def test_reappearance_is_suppressed_after_a_coverage_gap():
    det = detector()
    det.on_track(track(1, *OFFSHORE, T0), None)
    back = track(1, *OFFSHORE, T0 + timedelta(minutes=45))
    assert det.on_track(back, None, silence_was_coverage=True) == []
