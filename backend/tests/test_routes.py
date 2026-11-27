"""Route segmentation, stats and thinning (pure)."""

from datetime import UTC, datetime, timedelta

import pytest

from minicop.routes import RoutePoint, route_stats, split_segments, thin

T0 = datetime(2026, 11, 27, 2, 0, tzinfo=UTC)
NM_LAT = 1 / 60


def pt(minutes: float, north_nm: float = 0.0) -> RoutePoint:
    return RoutePoint(
        time=T0 + timedelta(minutes=minutes), lat=37.0 + north_nm * NM_LAT, lon=-8.5, sog=6, cog=0
    )


def test_gap_splits_the_route():
    points = [pt(0), pt(5, 0.5), pt(10, 1.0), pt(55, 4.0), pt(60, 4.5)]  # 45 min silence
    segments = split_segments(points)
    assert [len(s) for s in segments] == [3, 2]


def test_exactly_thirty_minutes_is_not_a_gap():
    assert len(split_segments([pt(0), pt(30, 3.0)])) == 1


def test_stats_exclude_gaps():
    # Segment 1: 1 nm in 10 min. Segment 2: 0.5 nm in 5 min. Gap of 45 min,
    # during which the ship "moved" 3 nm: not counted as travel or time.
    segments = split_segments([pt(0), pt(10, 1.0), pt(55, 4.0), pt(60, 4.5)])
    stats = route_stats(segments)
    assert stats.points == 4
    assert stats.distance_nm == pytest.approx(1.5, rel=0.01)
    assert stats.moving_time_s == 15 * 60
    assert stats.avg_speed_kn == pytest.approx(6.0, rel=0.01)  # 1.5 nm / 0.25 h
    assert stats.longest_gap_s == 45 * 60


def test_single_point_route():
    stats = route_stats(split_segments([pt(0)]))
    assert (stats.points, stats.distance_nm, stats.avg_speed_kn, stats.longest_gap_s) == (
        1,
        0,
        0,
        0,
    )


def test_thin_keeps_ends_and_respects_cap():
    points = [pt(m / 10) for m in range(12_000)]
    kept, thinned = thin(points, 5000)
    assert thinned and len(kept) == 5000
    assert kept[0] == points[0] and kept[-1] == points[-1]
    assert all(a.time < b.time for a, b in zip(kept, kept[1:], strict=False))


def test_thin_is_a_no_op_under_the_cap():
    points = [pt(m) for m in range(10)]
    assert thin(points, 5000) == (points, False)
