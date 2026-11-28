"""Regression tests for the review of the alert rules (drawn areas, speeding,
spoofing stand-in, impossible-position episodes). Each failed before the fix."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from minicop.alerts import AlertEngine
from minicop.anomalies import AnomalyDetector, load_anomaly_config
from minicop.api import create_app
from minicop.bathymetry import load_bathymetry
from minicop.config import Area
from minicop.context import ContextConfig, ContextMonitor
from minicop.events import PositionEvent, Track
from minicop.user_zones import UserZoneIn, polygon_problem
from minicop.zones import Zone

T0 = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
TRI = [[36.9, -8.5], [36.9, -8.4], [36.81, -8.45]]
B = load_bathymetry("algarve")
SHALLOW_8M = (37.1891, -7.2672)  # 8 m, no land within 500 m (from the grid)
COASTAL = (37.085, -8.40)  # coastal band: no verdict


def test_blank_name_is_refused_and_names_are_stripped():
    with pytest.raises(ValidationError):
        UserZoneIn(name="   ", kind="watch", polygon=TRI)
    assert UserZoneIn(name="  Night watch ", kind="watch", polygon=TRI).name == "Night watch"


def test_slash_and_control_characters_are_refused_in_names():
    for bad in ["Sagres/Lagos", "tab\there"]:
        with pytest.raises(ValidationError):
            UserZoneIn(name=bad, kind="watch", polygon=TRI)


def test_api_refuses_a_name_that_could_never_be_deleted():
    with TestClient(create_app(ingest=False, zones=[], bathymetry=None)) as client:
        r = client.post("/zones", json={"name": "Sagres/Lagos", "kind": "watch", "polygon": TRI})
        assert r.status_code == 422


def test_points_in_a_line_and_pinched_polygons_are_refused():
    assert "line" in (polygon_problem([(37.0, -8.0), (37.01, -8.0), (37.02, -8.0)], None) or "")
    # The 4th vertex lies on the first edge: the polygon pinches itself there.
    pinched = [(37.0, -8.0), (37.0, -7.9), (36.95, -7.95), (37.0, -7.95), (36.9, -7.9)]
    assert "touch" in (polygon_problem(pinched, None) or "")


def test_an_edge_between_two_boxes_must_stay_inside_them():
    # Two boxes side by side with a gap of open sea between them (lon -9 to -8):
    # every vertex is inside a box, but the long edges cross the gap.
    area = Area(
        name="two boxes", boxes=[((36.0, -10.0), (37.0, -9.0)), ((36.0, -8.0), (37.0, -7.0))]
    )
    poly = [(36.5, -9.5), (36.6, -7.5), (36.4, -7.5)]
    assert "leaves the monitored area" in (polygon_problem(poly, area) or "")


def test_sog_not_available_is_never_speeding():
    zone = Zone(name="Slow", kind="speed", alert_on_entry=False, max_speed_kn=10, polygon=TRI)
    engine = AlertEngine([zone])
    t = Track(
        mmsi=1,
        ship_name="X",
        latitude=36.87,
        longitude=-8.45,
        sog=102.3,
        cog=90,
        true_heading=511,
        navigational_status=0,
        last_seen=T0,
    )
    assert engine.on_track(t) == []
    assert [a.kind for a in engine.on_track(t.model_copy(update={"sog": 14.0}))] == ["speeding"]


def test_spoofing_stand_in_keeps_the_ais_class():
    event = PositionEvent(
        mmsi=5,
        latitude=36.9,
        longitude=-8.4,
        sog=5,
        cog=0,
        true_heading=511,
        navigational_status=0,
        ship_name="SMALL",
        received_at=T0,
        ais_class="B",
    )
    assert AnomalyDetector._track_from(event).ais_class == "B"
    assert load_anomaly_config()  # config still loads


def test_impossible_position_episode_survives_a_no_verdict_place():
    mon = ContextMonitor(
        ContextConfig(draught_margin_m=3, coast_margin_m=500), B, [], AlertEngine([])
    )

    def at(pos, minutes):
        return Track(
            mmsi=9,
            ship_name="SPOOF",
            latitude=pos[0],
            longitude=pos[1],
            sog=0,
            cog=360,
            true_heading=511,
            navigational_status=0,
            last_seen=T0 + timedelta(minutes=minutes),
            draught_m=10.6,
        )

    assert len(mon.on_track(at(SHALLOW_8M, 0))) == 1
    assert mon.on_track(at(COASTAL, 300)) == []  # no verdict here: still the same episode
    assert mon.on_track(at(SHALLOW_8M, 600)) == []  # not re-alerted
