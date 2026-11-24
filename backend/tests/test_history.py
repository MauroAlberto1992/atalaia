from datetime import datetime, timedelta, timezone

import pytest

from minicop.history import AddResult, ShipHistory

T0 = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
NM_LAT = 1 / 60  # one nautical mile north = 1 minute of latitude


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_distance_and_average_speed():
    h = ShipHistory()
    h.add(37.0, -8.0, at(0))
    h.add(37.0 + NM_LAT, -8.0, at(6))  # 1 nm in 6 min
    h.add(37.0 + 2 * NM_LAT, -8.0, at(12))  # another 1 nm
    s = h.stats()
    assert s.distance_nm == pytest.approx(2.0, rel=0.01)
    assert s.duration_s == 720
    assert s.avg_speed_kn == pytest.approx(10.0, rel=0.01)  # 2 nm / 0.2 h


def test_jitter_is_ignored():
    h = ShipHistory()
    h.add(37.0, -8.0, at(0))
    # ~5 m north: a moored ship's GPS noise
    assert h.add(37.0 + 5 / 1852 / 60, -8.0, at(1)) is AddResult.JITTER
    assert len(h.points()) == 1
    assert h.stats().distance_nm == 0.0


def test_single_jump_is_rejected():
    h = ShipHistory()
    h.add(37.0, -8.0, at(0))
    # 10 nm in 1 minute = 600 kn
    assert h.add(37.0 + 10 * NM_LAT, -8.0, at(1)) is AddResult.JUMP
    assert h.stats().distance_nm == 0.0
    # The ship carries on normally from the real position.
    assert h.add(37.0 + 0.1 * NM_LAT, -8.0, at(2)) is AddResult.ADDED


def test_repeated_jumps_are_eventually_accepted_without_distance():
    h = ShipHistory()
    h.add(37.0, -8.0, at(0))  # this was the bad position
    far = 37.0 + 10 * NM_LAT
    assert h.add(far, -8.0, at(1)) is AddResult.JUMP
    assert h.add(far + 0.01 * NM_LAT, -8.0, at(1.1)) is AddResult.JUMP
    assert h.add(far + 0.02 * NM_LAT, -8.0, at(1.2)) is AddResult.ADDED
    assert h.stats().distance_nm == 0.0  # the jump is not counted as travel


def test_eviction_subtracts_oldest_segment():
    h = ShipHistory(max_points=3)
    for i in range(4):  # 4 points, 1 nm apart -> oldest evicted
        h.add(37.0 + i * NM_LAT, -8.0, at(6 * i))
    assert len(h.points()) == 3
    assert h.stats().distance_nm == pytest.approx(2.0, rel=0.01)
    assert h.stats().duration_s == 720


def test_stats_with_one_point():
    h = ShipHistory()
    h.add(37.0, -8.0, at(0))
    assert h.stats().avg_speed_kn == 0.0
