import pytest

from minicop.geo import haversine_nm


def test_one_minute_of_latitude_is_one_nautical_mile():
    assert haversine_nm(37.0, -8.0, 37.0 + 1 / 60, -8.0) == pytest.approx(1.0, rel=0.01)


def test_lisbon_to_porto():
    # Lisbon (38.7223, -9.1393) to Porto (41.1579, -8.6291): ~274 km = ~148 nm.
    assert haversine_nm(38.7223, -9.1393, 41.1579, -8.6291) == pytest.approx(148, rel=0.01)


def test_same_point_is_zero():
    assert haversine_nm(37.0, -8.0, 37.0, -8.0) == 0.0
