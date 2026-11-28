"""Regression tests for the review of the fusion and the simulated sensor.
Each failed before the fix."""

import math
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from minicop.events import Track
from minicop.fusion import FusionEngine, associate, explain_by_ais
from minicop.geo import haversine_nm
from minicop.sensors import Detection, DroneSimulator, FusionConfig, Sweep, load_sensors_config

CFG = load_sensors_config()
F = CFG.fusion
T0 = datetime(2026, 11, 28, 14, 0, tzinfo=UTC)
SEA = (36.85, -8.45)


def east(lat: float, lon: float, nm: float) -> tuple[float, float]:
    return lat, lon + nm / (60 * math.cos(math.radians(lat)))


def north(lat: float, lon: float, nm: float) -> tuple[float, float]:
    return lat + nm / 60, lon


def track(lat: float, lon: float, t: datetime, sog: float = 12.0, cog: float = 90.0) -> Track:
    return Track(
        mmsi=7,
        ship_name="X",
        latitude=lat,
        longitude=lon,
        sog=sog,
        cog=cog,
        true_heading=511,
        navigational_status=0,
        last_seen=t,
    )


def det(lat: float, lon: float, t: datetime) -> Detection:
    return Detection(time=t, lat=lat, lon=lon, sigma_m=150, sensor_id="T")


def sweep(t: datetime, dets: list[Detection]) -> Sweep:
    return Sweep(time=t, sensor_id="T", lat=SEA[0], lon=SEA[1], footprint_nm=5, detections=dets)


def test_a_report_made_after_the_contact_still_explains_it():
    # Contact last seen at T0; the ship reports 5 min later, 1 nm on (12 kn).
    later = track(*east(*SEA, 1.0), T0 + timedelta(minutes=5))
    got = explain_by_ais(*SEA, T0, [later], F)
    assert got is not None and got[1] == pytest.approx(5)


def test_a_report_slightly_ahead_of_the_local_clock_is_associated():
    ahead = track(*SEA, T0 + timedelta(seconds=3))  # aisstream clock 3 s ahead
    matched, unmatched = associate([det(*SEA, T0)], [ahead], T0, F)
    assert matched == {0: 7} and unmatched == []


def test_a_contact_unseen_for_minutes_does_not_take_a_far_detection():
    eng = FusionEngine(F)
    for k in range(4):  # a stationary contact, confirmed
        t = T0 + timedelta(seconds=30 * k)
        eng.process(sweep(t, [det(*SEA, t)]), [])
    t = T0 + timedelta(minutes=10)  # 8+ min later, 5 nm away
    eng.process(sweep(t, [det(*east(*SEA, 5.0), t)]), [])
    assert len(eng._candidates) == 2  # a new candidate, not a jump of the old one


def test_speed_comes_from_recent_detections_not_the_whole_loop():
    eng = FusionEngine(F)
    # 20 min looping back to the start at 3 kn, then 6 min going east at 6 kn.
    pts: list[tuple[datetime, tuple[float, float]]] = []
    for k in range(40):
        a = 2 * math.pi * k / 40
        r = 0.5 * (1 - math.cos(a))  # out and back, ~1 nm, ends where it started
        pts.append((T0 + timedelta(seconds=30 * k), north(*SEA, r)))
    for k in range(1, 13):
        pts.append((T0 + timedelta(minutes=20, seconds=30 * k), east(*SEA, 6 * 30 * k / 3600)))
    for t, p in pts:
        eng.process(sweep(t, [det(*p, t)]), [])
    dark = eng.process(sweep(pts[-1][0] + timedelta(seconds=1), []), []).dark
    assert dark and dark[0].sog is not None
    assert 3 < dark[0].sog < 9  # recent ~6 kn east, not ~1 kn net over the loop


def test_one_implausible_point_cannot_block_confirmation_with_fast_sweeps():
    eng = FusionEngine(F)
    t = T0
    eng.process(sweep(t, [det(*SEA, t)]), [])
    t2 = t + timedelta(seconds=1)  # 1 s sweeps (the fast demo)
    eng.process(sweep(t2, [det(*east(*SEA, 0.5), t2)]), [])  # 0.5 nm in 1 s: not a ship
    confirmed = []
    for k in range(2, 6):
        tk = t + timedelta(seconds=k)
        confirmed += eng.process(sweep(tk, [det(*SEA, tk)]), []).newly_confirmed
    assert confirmed  # the real contact still confirms


def test_simulator_detects_a_ship_where_it_is_now_not_where_it_reported():
    cfg = CFG.model_copy(
        update={
            "drone": CFG.drone.model_copy(
                update={"pd": 1.0, "position_sigma_m": 0.0, "false_alarms_per_sweep": 0.0}
            ),
            "dark_targets": [],
        }
    )
    sim = DroneSimulator(cfg, T0)
    lat0, lon0 = sim.drone_position(T0)
    reported = track(lat0, lon0, T0 - timedelta(minutes=5))  # 12 kn east, 5 min ago
    (d,) = sim.sweep(T0, [reported]).detections
    assert haversine_nm(lat0, lon0, d.lat, d.lon) == pytest.approx(1.0, rel=0.02)


def test_impossible_fusion_settings_are_refused():
    good = F.model_dump()
    with pytest.raises(ValidationError):
        FusionConfig(**{**good, "confirm_hits": 6, "confirm_window": 5})
    with pytest.raises(ValidationError):
        FusionConfig(**{**good, "explain_base_nm": 0})
