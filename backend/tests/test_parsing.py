import json
from pathlib import Path

from minicop.parsing import parse_position

FIXTURE = (Path(__file__).parent / "fixtures" / "position_report.json").read_text()


def _with(**changes) -> str:
    """Return the fixture with fields of the inner PositionReport replaced."""
    data = json.loads(FIXTURE)
    data["Message"]["PositionReport"].update(changes)
    return json.dumps(data)


def test_parses_valid_position_report():
    report = parse_position(FIXTURE)
    assert report is not None
    assert report.mmsi == 263123456
    assert report.latitude == 37.0123
    assert report.longitude == -7.9345
    assert report.sog == 11.2
    assert report.true_heading == 247


def test_accepts_bytes():
    assert parse_position(FIXTURE.encode()) is not None


def test_ignores_other_message_types():
    data = json.loads(FIXTURE)
    data["MessageType"] = "ShipStaticData"
    data["Message"] = {"ShipStaticData": {}}
    assert parse_position(json.dumps(data)) is None


def test_rejects_unavailable_position():
    assert parse_position(_with(Latitude=91, Longitude=181)) is None


def test_rejects_out_of_range_longitude():
    assert parse_position(_with(Longitude=-200)) is None


def test_malformed_json_returns_none():
    assert parse_position("{not json") is None


def test_missing_field_returns_none():
    data = json.loads(FIXTURE)
    del data["Message"]["PositionReport"]["UserID"]
    assert parse_position(json.dumps(data)) is None
