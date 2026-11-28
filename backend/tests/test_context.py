"""Phase 17a: static AIS data, ship types, depth on tracks, impossible positions.

Static frames are the real ones captured from aisstream (tests/fixtures/captured).
Test positions come from the committed EMODnet cut; each depth below was read
from it (see test_bathymetry.py for the cut checked against the source tile).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from minicop.alerts import AlertEngine
from minicop.bathymetry import load_bathymetry
from minicop.context import ContextConfig, ContextMonitor, impossible_reason
from minicop.events import PositionEvent, StaticEvent, Track
from minicop.parsing import parse_static
from minicop.ship_types import ship_type_label
from minicop.state import TrackStore
from minicop.zones import Zone

CAPTURED = Path(__file__).parent / "fixtures" / "captured"
B = load_bathymetry("algarve")
CFG = ContextConfig(draught_margin_m=3.0, coast_margin_m=500)
T0 = datetime(2026, 11, 28, 4, 0, tzinfo=UTC)

# From the grid: shallow shelf off Isla Cristina (east of the Guadiana), 8 m,
# no land within 500 m.
SHALLOW_8M = (37.1891, -7.2672)
OFFSHORE_25M = (37.06, -8.40)  # 25 m, ~2.5 km off the coast near Vilamoura
COASTAL = (37.085, -8.40)  # land and sea both within 500 m: can't tell
INLAND = (37.20, -8.00)  # Algarve hills


def frame(name: str) -> str:
    return (CAPTURED / name).read_text()


# ---- parsing (real frames) ------------------------------------------------------


def test_class_a_static_gives_type_and_draught_in_metres():
    e = parse_static(frame("ShipStaticData_3.json"))  # GLORIOUS MAPLE, cargo
    assert e == StaticEvent(mmsi=370732000, ship_type=70, draught_m=10.6)


def test_class_b_part_a_is_ignored_and_part_b_gives_the_type():
    assert parse_static(frame("StaticDataReport_1.json")) is None  # part A: name only
    e = parse_static(frame("StaticDataReport_5.json"))
    assert e == StaticEvent(mmsi=225987240, ship_type=36, draught_m=None)  # sailing


def test_position_frames_are_not_static():
    assert parse_static(frame("PositionReport_1.json")) is None


def test_ship_type_labels():
    assert ship_type_label(30) == "Fishing"
    assert ship_type_label(36) == "Sailing"
    assert ship_type_label(52) == "Tug"
    assert ship_type_label(70) == ship_type_label(79) == "Cargo"
    assert ship_type_label(80) == "Tanker"
    assert ship_type_label(None) == ship_type_label(0) == ""
    assert ship_type_label(7) == "Unknown (7)"  # seen in the captured sample (ELMAR DOS)


# ---- state ----------------------------------------------------------------------


def position(mmsi: int, lat: float, lon: float, t: datetime = T0) -> PositionEvent:
    return PositionEvent(
        mmsi=mmsi,
        latitude=lat,
        longitude=lon,
        sog=10.0,
        cog=90.0,
        true_heading=511,
        navigational_status=0,
        ship_name="TEST",
        received_at=t,
    )


def test_static_before_position_and_depth_on_the_track():
    store = TrackStore(B)
    assert (
        store.apply_static(StaticEvent(mmsi=1, ship_type=70, draught_m=10.6)) is None
    )  # not on map yet
    track = store.apply(position(1, *OFFSHORE_25M))
    assert track is not None
    assert (track.ship_type, track.ship_type_label, track.draught_m) == (70, "Cargo", 10.6)
    assert track.depth_m == 25


def test_class_b_type_does_not_erase_a_known_draught():
    store = TrackStore(B)
    store.apply(position(2, *OFFSHORE_25M))
    store.apply_static(StaticEvent(mmsi=2, ship_type=70, draught_m=4.4))
    updated = store.apply_static(StaticEvent(mmsi=2, ship_type=36))
    assert updated is not None and updated.draught_m == 4.4 and updated.ship_type == 36
    assert store.apply_static(StaticEvent(mmsi=2, ship_type=36)) is None  # nothing changed


def test_no_bathymetry_means_no_depth():
    track = TrackStore(None).apply(position(3, *OFFSHORE_25M))
    assert track is not None and track.depth_m is None


# ---- impossible positions -------------------------------------------------------


def ship(lat: float, lon: float, draught: float | None, mmsi: int = 9, t: datetime = T0) -> Track:
    return Track(
        mmsi=mmsi,
        ship_name="GLORIOUS MAPLE",
        latitude=lat,
        longitude=lon,
        sog=10.0,
        cog=90.0,
        true_heading=511,
        navigational_status=0,
        last_seen=t,
        draught_m=draught,
    )


def test_deeper_draught_than_the_sea_is_impossible():
    assert B is not None
    reason = impossible_reason(ship(*SHALLOW_8M, draught=10.6), B, CFG, [])
    assert reason is not None and "depth ~8 m" in reason and "10.6 m" in reason


def test_shallow_draught_there_is_fine_and_unknown_draught_says_nothing():
    assert B is not None
    assert impossible_reason(ship(*SHALLOW_8M, draught=4.4), B, CFG, []) is None  # 8 >= 4.4 + 3
    assert impossible_reason(ship(*SHALLOW_8M, draught=None), B, CFG, []) is None


def test_inland_position_is_impossible_but_the_coast_and_ports_are_not_judged():
    assert B is not None
    assert "on land" in (impossible_reason(ship(*INLAND, draught=None), B, CFG, []) or "")
    assert impossible_reason(ship(*COASTAL, draught=30.0), B, CFG, []) is None
    port = Zone(
        name="Test port", kind="port", polygon=[(37.19, -7.27), (37.19, -7.26), (37.18, -7.265)]
    )
    assert impossible_reason(ship(*SHALLOW_8M, draught=10.6), B, CFG, [port]) is None


def test_outside_the_grid_says_nothing():
    assert B is not None
    assert (
        impossible_reason(ship(38.7, -9.4, draught=50.0), B, CFG, []) is None
    )  # Lisbon: not in the cut


def test_monitor_alerts_once_per_episode_and_re_arms():
    engine = AlertEngine([])
    mon = ContextMonitor(CFG, B, [], engine)
    first = mon.on_track(ship(*SHALLOW_8M, draught=10.6))
    assert [a.kind for a in first] == ["impossible_position"]
    assert "Aground, or a wrong/spoofed position" in first[0].message
    assert mon.on_track(ship(*SHALLOW_8M, draught=10.6, t=T0 + timedelta(minutes=1))) == []
    # The two points are ~48 nm apart: 5 h at ~10 kn each way.
    assert mon.on_track(ship(*OFFSHORE_25M, draught=10.6, t=T0 + timedelta(hours=5))) == []
    again = mon.on_track(ship(*SHALLOW_8M, draught=10.6, t=T0 + timedelta(hours=10)))
    assert len(again) == 1


def test_bathymetry_endpoints():
    from fastapi.testclient import TestClient

    from minicop.api import create_app

    with TestClient(create_app(ingest=False, zones=[], bathymetry=B)) as client:
        info = client.get("/bathymetry").json()
        assert info["available"] and "CC BY 4.0" in info["attribution"]
        assert "Not for navigation" in info["attribution"]
        assert len(info["grids"]) == 1 and info["grids"][0]["north"] > 37.3
        png = client.get("/bathymetry/0.png")
        assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
        assert client.get("/bathymetry/1.png").status_code == 404
    with TestClient(create_app(ingest=False, zones=[], bathymetry=None)) as client:
        assert client.get("/bathymetry").json() == {"available": False}
