from datetime import UTC, datetime
from pathlib import Path

import pytest

from minicop.parsing import parse_aisstream_time, parse_event

FIXTURE = (Path(__file__).parent / "fixtures" / "position_report.json").read_text()


def test_parse_time_truncates_nanoseconds_to_utc():
    t = parse_aisstream_time("2026-11-24 21:30:12.123456789 +0000 UTC")
    assert t == datetime(2026, 11, 24, 21, 30, 12, 123456, tzinfo=UTC)


def test_parse_time_short_fraction():
    t = parse_aisstream_time("2026-11-24 21:30:12.5 +0000 UTC")
    assert t.microsecond == 500000


def test_parse_time_rejects_garbage():
    with pytest.raises(ValueError):
        parse_aisstream_time("yesterday")


def test_parse_event_builds_event_with_metadata():
    event = parse_event(FIXTURE)
    assert event is not None
    assert event.mmsi == 263123456
    assert event.ship_name == "EXAMPLE VESSEL"  # trailing AIS padding stripped
    assert event.received_at.tzinfo is not None
