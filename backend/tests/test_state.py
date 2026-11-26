from datetime import UTC, datetime, timedelta

from minicop.events import PositionEvent
from minicop.state import TrackStore

T0 = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def event(mmsi=263123456, lat=37.0, lon=-8.0, at=T0, name="SHIP") -> PositionEvent:
    return PositionEvent(
        mmsi=mmsi,
        latitude=lat,
        longitude=lon,
        sog=10.0,
        cog=90.0,
        true_heading=90,
        navigational_status=0,
        ship_name=name,
        received_at=at,
    )


def test_new_ship_creates_track():
    store = TrackStore()
    track = store.apply(event())
    assert track is not None and track.mmsi == 263123456
    assert len(store) == 1


def test_newer_report_updates_track():
    store = TrackStore()
    store.apply(event())
    track = store.apply(event(lat=37.1, at=T0 + timedelta(minutes=10)))  # 6 nm in 10 min
    assert track is not None and track.latitude == 37.1
    assert len(store) == 1


def test_older_or_duplicate_report_is_ignored():
    store = TrackStore()
    store.apply(event(lat=37.1, at=T0))
    assert store.apply(event(lat=36.0, at=T0 - timedelta(seconds=5))) is None
    assert store.apply(event(lat=36.0, at=T0)) is None
    assert store.snapshot()[0].latitude == 37.1


def test_empty_name_keeps_known_name():
    store = TrackStore()
    store.apply(event(name="SHIP"))
    track = store.apply(event(name="", at=T0 + timedelta(seconds=1)))
    assert track.ship_name == "SHIP"


def test_ships_are_tracked_separately():
    store = TrackStore()
    store.apply(event(mmsi=1))
    store.apply(event(mmsi=2))
    assert {t.mmsi for t in store.snapshot()} == {1, 2}


def test_track_carries_history_stats():
    store = TrackStore()
    store.apply(event(lat=37.0, at=T0))
    track = store.apply(event(lat=37.0 + 1 / 60, at=T0 + timedelta(minutes=6)))
    assert round(track.distance_nm, 2) == 1.0
    assert round(track.avg_speed_kn) == 10


def test_jump_does_not_move_the_track():
    store = TrackStore()
    store.apply(event(lat=37.0, at=T0))
    assert store.apply(event(lat=38.0, at=T0 + timedelta(seconds=10))) is None
    assert store.snapshot()[0].latitude == 37.0


def test_jitter_still_updates_last_seen():
    store = TrackStore()
    store.apply(event(lat=37.0, at=T0))
    track = store.apply(event(lat=37.0, at=T0 + timedelta(seconds=10)))
    assert track is not None and track.last_seen == T0 + timedelta(seconds=10)


def test_silent_ship_becomes_stale_once():
    store = TrackStore()
    store.apply(event(at=T0))
    assert store.sweep(T0 + timedelta(minutes=5)).stale == []
    assert store.sweep(T0 + timedelta(minutes=10)).stale == [263123456]
    assert store.snapshot()[0].stale
    assert store.sweep(T0 + timedelta(minutes=11)).stale == []  # not reported twice


def test_stale_ship_that_reports_again_is_fresh():
    store = TrackStore()
    store.apply(event(at=T0))
    store.sweep(T0 + timedelta(minutes=15))
    track = store.apply(event(at=T0 + timedelta(minutes=16)))
    assert track is not None and not track.stale


def test_long_silent_ship_is_removed_with_history():
    store = TrackStore()
    store.apply(event(at=T0))
    result = store.sweep(T0 + timedelta(minutes=60))
    assert result.removed == [263123456]
    assert len(store) == 0
    assert store.history(263123456) is None


def test_counters_explain_every_report():
    store = TrackStore()
    store.apply(event(lat=37.0, at=T0))  # accepted
    store.apply(event(lat=37.0, at=T0))  # same time: out of order
    store.apply(event(lat=38.0, at=T0 + timedelta(seconds=10)))  # 60 nm in 10 s: jump
    assert (store.accepted, store.out_of_order, store.jumps_rejected) == (1, 1, 1)
