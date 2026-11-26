"""Class A and Class B parsing against frames captured from aisstream on
2026-11-26 (scripts/watch_positions.py --save 5). Message 19
(ExtendedClassBPositionReport) did not appear in 20 min, so it has no real
fixture; it shares the parsing path with message 18."""

from pathlib import Path

import pytest

from minicop.parsing import parse_event, parse_position

CAPTURED = Path(__file__).parent / "fixtures" / "captured"
CLASS_A = sorted(CAPTURED.glob("PositionReport_*.json"))
CLASS_B = sorted(CAPTURED.glob("StandardClassBPositionReport_*.json"))


def test_fixtures_were_captured():
    assert len(CLASS_A) == 5 and len(CLASS_B) == 5


@pytest.mark.parametrize("path", CLASS_A, ids=lambda p: p.name)
def test_real_class_a_frames_parse(path):
    report = parse_position(path.read_text())
    assert report is not None and report.ais_class == "A"


@pytest.mark.parametrize("path", CLASS_B, ids=lambda p: p.name)
def test_real_class_b_frames_parse(path):
    report = parse_position(path.read_text())
    assert report is not None
    assert report.ais_class == "B"
    assert report.navigational_status == 15  # Class B carries no status: "not defined"


def test_class_b_event_keeps_class_and_empty_name():
    # Seen in the capture: Class B MetaData.ShipName is empty (the name comes in
    # a separate message, type 24, which we don't subscribe to).
    event = parse_event(CLASS_B[0].read_text())
    assert event is not None
    assert event.ais_class == "B"
    assert event.ship_name == ""
