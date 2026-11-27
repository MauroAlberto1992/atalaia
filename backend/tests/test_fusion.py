"""AIS + sensor fusion: prediction, gating, association, M-of-N confirmation."""

import math
import random
from datetime import UTC, datetime, timedelta

import pytest

from minicop.events import Track
from minicop.fusion import FusionEngine, associate, dead_reckon, gate_nm
from minicop.geo import haversine_nm
from minicop.sensors import (
    Detection,
    DroneSimulator,
    Sweep,
    load_sensors_config,
    position_along,
)

CFG = load_sensors_config()
F = CFG.fusion
T0 = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
SEA = (36.85, -8.45)


def track(mmsi: int, lat: float, lon: float, t: datetime = T0, sog=10.0, cog=90.0) -> Track:
    return Track(
        mmsi=mmsi,
        ship_name=f"S{mmsi}",
        latitude=lat,
        longitude=lon,
        sog=sog,
        cog=cog,
        true_heading=511,
        navigational_status=0,
        last_seen=t,
    )


def det(lat: float, lon: float, t: datetime = T0, truth: str | None = None) -> Detection:
    return Detection(time=t, lat=lat, lon=lon, sigma_m=150, sensor_id="T", truth=truth)


def east(lat: float, lon: float, nm: float) -> tuple[float, float]:
    return lat, lon + nm / (60 * math.cos(math.radians(lat)))


# ---- prediction and gating ------------------------------------------------------


def test_dead_reckoning_10_kn_east_for_6_min_is_1_nm():
    lat, lon = dead_reckon(track(1, *SEA, sog=10, cog=90), T0 + timedelta(minutes=6))
    assert haversine_nm(*SEA, lat, lon) == pytest.approx(1.0, rel=0.01)
    assert lat == pytest.approx(SEA[0], abs=1e-6)


def test_unknown_course_stays_put():
    assert dead_reckon(track(1, *SEA, cog=360), T0 + timedelta(minutes=6)) == SEA


def test_gate_grows_with_age_up_to_a_cap():
    assert gate_nm(F, timedelta(0)) == F.gate_nm
    assert gate_nm(F, timedelta(minutes=5)) == pytest.approx(
        F.gate_nm + 5 * F.gate_growth_nm_per_min
    )
    assert gate_nm(F, timedelta(hours=5)) == F.gate_max_nm


# ---- association ----------------------------------------------------------------


def test_two_ships_two_detections_pair_correctly():
    a, b = track(1, *SEA), track(2, *east(*SEA, 3.0))
    dets = [det(*east(*SEA, 3.05)), det(*east(*SEA, 0.05))]  # listed "crossed"
    matched, unmatched = associate(dets, [a, b], T0, F)
    assert matched == {0: 2, 1: 1} and unmatched == []


def test_contested_detection_goes_to_the_nearer_ship_and_is_used_once():
    a, b = track(1, *SEA), track(2, *east(*SEA, 0.4))
    dets = [det(*east(*SEA, 0.3))]  # within both gates, nearer to ship 2
    matched, _ = associate(dets, [a, b], T0, F)
    assert matched == {0: 2}


def test_detection_outside_the_gate_is_unassociated():
    matched, unmatched = associate([det(*east(*SEA, 1.0))], [track(1, *SEA)], T0, F)
    assert matched == {} and unmatched == [0]


def test_old_ais_track_is_not_used():
    old = track(1, *SEA, t=T0 - timedelta(minutes=F.track_max_age_min + 1), sog=0)
    matched, _ = associate([det(*SEA)], [old], T0, F)
    assert matched == {}


def test_moving_ship_is_matched_at_its_predicted_position():
    # Last AIS 6 min ago at SEA, 10 kn east: now ~1 nm east, outside a static 0.5 nm gate.
    ship = track(1, *SEA, t=T0 - timedelta(minutes=6), sog=10, cog=90)
    matched, _ = associate([det(*east(*SEA, 1.0))], [ship], T0, F)
    assert matched == {0: 1}


# ---- confirmation -----------------------------------------------------------------


def sweep(t: datetime, dets: list[Detection]) -> Sweep:
    return Sweep(time=t, sensor_id="T", lat=SEA[0], lon=SEA[1], footprint_nm=5, detections=dets)


def test_dark_target_confirmed_after_3_of_5_sweeps():
    eng = FusionEngine(F)
    confirmed_at = None
    for k in range(6):  # 6 kn east, one sweep every 30 s, missed on sweep 1
        t = T0 + timedelta(seconds=30 * k)
        pos = east(*SEA, 6 * 30 * k / 3600)
        dets = [] if k == 1 else [det(*pos, t)]
        out = eng.process(sweep(t, dets), tracks=[])
        if out.newly_confirmed:
            confirmed_at = k
            # 1.5 min of detections: too short to report a speed honestly.
            assert out.newly_confirmed[0].sog is None
    assert confirmed_at == 3  # hits on sweeps 0, 2, 3


def test_real_ais_ship_is_fused_never_dark():
    eng = FusionEngine(F)
    ship = track(1, *SEA, sog=0, cog=360)
    for k in range(10):
        t = T0 + timedelta(seconds=30 * k)
        out = eng.process(
            sweep(t, [det(*SEA, t)]), tracks=[ship.model_copy(update={"last_seen": t})]
        )
        assert out.fused == {1: t}
        assert out.dark == []


def test_random_clutter_rarely_confirms():
    """M-of-N has a non-zero false-confirmation rate: three clutter points can
    land close together by chance. With 1 clutter point per sweep (twice the
    configured rate) over 5 h, at most one false dark track is accepted. The
    measured rate is reported in the phase summary as a known weakness."""
    rng = random.Random(1)
    eng = FusionEngine(F)
    false_confirms = 0
    for k in range(600):  # 5 h of sweeps
        t = T0 + timedelta(seconds=30 * k)
        r, a = 5 * math.sqrt(rng.random()), rng.random() * 2 * math.pi
        lat = SEA[0] + r * math.cos(a) / 60
        lon = SEA[1] + r * math.sin(a) / (60 * math.cos(math.radians(SEA[0])))
        out = eng.process(sweep(t, [det(lat, lon, t, "clutter")]), tracks=[])
        false_confirms += len(out.newly_confirmed)
    assert false_confirms <= 1


def test_dark_track_is_dropped_after_silence():
    eng = FusionEngine(F)
    for k in range(3):
        t = T0 + timedelta(seconds=30 * k)
        eng.process(sweep(t, [det(*SEA, t)]), tracks=[])
    later = T0 + timedelta(minutes=F.drop_after_min + 2)
    assert eng.process(sweep(later, []), tracks=[]).dark == []


# ---- simulator ----------------------------------------------------------------------


def test_position_along_a_loop_wraps():
    square = [(36.0, -8.0), (36.0, -7.9), (36.1, -7.9), (36.1, -8.0)]
    total = sum(
        haversine_nm(*a, *b)
        for a, b in zip([*square, square[0]], [*square[1:], square[0]], strict=False)
    )
    assert position_along(square, total + 0.0, loop=True) == pytest.approx(square[0])


def test_simulator_sees_ships_and_dark_targets_in_its_footprint_only():
    sim = DroneSimulator(CFG, T0)
    lat0, lon0 = sim.drone_position(T0)
    near = track(1, lat0, lon0)  # under the drone
    far = track(2, lat0 + 1.0, lon0)  # 60 nm north
    truths = []
    for k in range(40):
        s = sim.sweep(
            T0 + timedelta(seconds=30 * k), [near.model_copy(update={"last_seen": T0}), far]
        )
        truths += [d.truth for d in s.detections]
    assert "ais:2" not in truths
    assert truths.count("ais:1") > 0  # Pd 0.9, but the drone moves away over 20 min


def test_speed_is_reported_once_detections_span_3_minutes():
    eng = FusionEngine(F)
    out = None
    for k in range(8):  # 6 kn east, every 30 s, for 3.5 min
        t = T0 + timedelta(seconds=30 * k)
        out = eng.process(sweep(t, [det(*east(*SEA, 6 * 30 * k / 3600), t)]), tracks=[])
    assert out is not None and out.dark[0].sog == pytest.approx(6, rel=0.1)
    assert out.dark[0].cog == pytest.approx(90, abs=5)


def test_implausible_hop_blocks_confirmation():
    eng = FusionEngine(F)
    # Middle detection 0.34 nm away 30 s later (about 41 kn): not a ship.
    for k, pos in enumerate([SEA, east(*SEA, 0.34), SEA]):
        t = T0 + timedelta(seconds=30 * k)
        out = eng.process(sweep(t, [det(*pos, t)]), tracks=[])
        assert out.newly_confirmed == []
