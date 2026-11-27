from datetime import UTC, datetime, timedelta

from minicop.alerts import AlertEngine, AlertKind
from minicop.events import Track
from minicop.zones import Zone, load_zones

T0 = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)

BOX = [(37.0, -8.0), (37.0, -7.9), (37.1, -7.9), (37.1, -8.0)]
RESTRICTED = Zone(name="R", kind="restricted", alert_on_entry=True, polygon=BOX)
SPEED = Zone(name="S", kind="speed", max_speed_kn=6, polygon=BOX)
INSIDE, OUTSIDE = (37.05, -7.95), (36.5, -7.95)


def track(pos, sog=3.0, mmsi=1, seconds=0) -> Track:
    return Track(
        mmsi=mmsi,
        ship_name="SHIP",
        latitude=pos[0],
        longitude=pos[1],
        sog=sog,
        cog=0,
        true_heading=511,
        navigational_status=0,
        last_seen=T0 + timedelta(seconds=seconds),
    )


def kinds(alerts):
    return [a.kind for a in alerts]


def test_enter_and_exit():
    e = AlertEngine([RESTRICTED])
    assert e.on_track(track(OUTSIDE)) == []
    assert kinds(e.on_track(track(INSIDE, seconds=1))) == [AlertKind.ENTER]
    assert e.on_track(track(INSIDE, seconds=2)) == []  # still inside: nothing new
    assert kinds(e.on_track(track(OUTSIDE, seconds=3))) == [AlertKind.EXIT]


def test_first_seen_inside_counts_as_enter():
    e = AlertEngine([RESTRICTED])
    assert kinds(e.on_track(track(INSIDE))) == [AlertKind.ENTER]


def test_zone_without_entry_alerts_is_silent_on_entry():
    e = AlertEngine([SPEED])
    assert e.on_track(track(INSIDE, sog=3)) == []


def test_speeding_alerts_once_per_visit():
    e = AlertEngine([SPEED])
    assert kinds(e.on_track(track(INSIDE, sog=9))) == [AlertKind.SPEEDING]
    assert e.on_track(track(INSIDE, sog=10, seconds=1)) == []  # same visit
    e.on_track(track(OUTSIDE, seconds=2))
    assert kinds(e.on_track(track(INSIDE, sog=9, seconds=3))) == [AlertKind.SPEEDING]


def test_speed_at_limit_is_fine():
    e = AlertEngine([SPEED])
    assert e.on_track(track(INSIDE, sog=6)) == []


def test_dark_only_inside_a_zone():
    e = AlertEngine([RESTRICTED])
    e.on_track(track(INSIDE, mmsi=1))
    e.on_track(track(OUTSIDE, mmsi=2))
    assert kinds(e.on_stale(track(INSIDE, mmsi=1), T0)) == [AlertKind.DARK]
    assert e.on_stale(track(OUTSIDE, mmsi=2), T0) == []


def test_removed_ship_raises_no_exit():
    e = AlertEngine([RESTRICTED])
    e.on_track(track(INSIDE))
    e.on_removed(1)
    # Comes back outside: no EXIT, since we forgot it was inside.
    assert e.on_track(track(OUTSIDE, seconds=1)) == []


def test_recent_is_newest_first_and_bounded():
    e = AlertEngine([RESTRICTED], max_alerts=3)
    for i in range(5):
        e.on_track(track(INSIDE if i % 2 == 0 else OUTSIDE, seconds=i))
    recent = e.recent()
    assert len(recent) == 3
    assert [a.id for a in recent] == [5, 4, 3]


def test_config_zones_load():
    # Phase 16: the last demo zone was removed; operators draw their own areas.
    assert load_zones() == []


def test_no_dark_alert_in_a_port_even_inside_another_zone():
    """Phase 11 change: switching AIS off in (or next to) a port is normal, so
    no "dark" at all there. (Before, a ship inside both a port and a restricted
    zone still went "dark" for the restricted zone.)"""
    port = Zone(name="P", kind="port", polygon=BOX)
    e = AlertEngine([port, RESTRICTED])
    e.on_track(track(INSIDE))
    assert e.on_stale(track(INSIDE), T0) == []
