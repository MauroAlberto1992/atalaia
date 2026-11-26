"""Recorder buffer logic, without a database."""

from datetime import UTC, datetime, timedelta

from minicop.events import Track
from minicop.recorder import RecordBuffer

T0 = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def track(mmsi: int, seconds: int, name: str = "SHIP") -> Track:
    return Track(
        mmsi=mmsi,
        ship_name=name,
        latitude=37.0,
        longitude=-8.0,
        sog=5,
        cog=90,
        true_heading=511,
        navigational_status=0,
        last_seen=T0 + timedelta(seconds=seconds),
    )


def test_take_returns_oldest_first_in_batches():
    buf = RecordBuffer()
    for s in range(5):
        buf.add(track(1, s))
    rows, _ = buf.take(3)
    assert [r[0] for r in rows] == [T0 + timedelta(seconds=s) for s in range(3)]
    assert len(buf) == 2


def test_overflow_drops_the_oldest_and_counts():
    buf = RecordBuffer(max_rows=3)
    for s in range(5):
        buf.add(track(1, s))
    rows, _ = buf.take(10)
    assert [r[0].second for r in rows] == [2, 3, 4]  # 0 and 1 were dropped
    assert buf.dropped == 2


def test_failed_write_puts_rows_back_in_order():
    buf = RecordBuffer()
    for s in range(4):
        buf.add(track(1, s))
    rows, names = buf.take(3)
    buf.add(track(1, 10))  # arrives while the write is failing
    buf.put_back(rows, names)
    again, _ = buf.take(10)
    assert [r[0].second for r in again] == [0, 1, 2, 3, 10]


def test_put_back_drops_old_rows_when_new_ones_filled_the_buffer():
    buf = RecordBuffer(max_rows=3)
    for s in range(3):
        buf.add(track(1, s))
    rows, names = buf.take(3)
    for s in (10, 11, 12):  # buffer full again with newer rows
        buf.add(track(1, s))
    buf.put_back(rows, names)
    again, _ = buf.take(10)
    assert [r[0].second for r in again] == [10, 11, 12]  # live data has priority
    assert buf.dropped == 3


def test_latest_name_per_ship_is_kept():
    buf = RecordBuffer()
    buf.add(track(1, 0, name="OLD"))
    buf.add(track(1, 5, name="NEW"))
    buf.add(track(2, 1, name="OTHER"))
    _, names = buf.take(10)
    assert names == {1: ("NEW", T0 + timedelta(seconds=5)), 2: ("OTHER", T0 + timedelta(seconds=1))}
