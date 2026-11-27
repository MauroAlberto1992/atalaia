"""API tests with fake events: no aisstream, no API key."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from minicop.api import create_app
from minicop.events import PositionEvent, Tick
from minicop.zones import Zone


def event(mmsi: int, second: int = 0) -> PositionEvent:
    return PositionEvent(
        mmsi=mmsi,
        latitude=37.0,
        longitude=-8.0,
        sog=5.0,
        cog=0.0,
        true_heading=0,
        navigational_status=0,
        ship_name="TEST",
        received_at=datetime(2026, 11, 24, 12, 0, second, tzinfo=UTC),
    )


async def feed(app, *events: PositionEvent) -> None:
    """Put events on the queue and wait until the state task has applied them."""
    for e in events:
        await app.state.runtime.events.put(e)
    await app.state.runtime.events.join()


def test_tracks_snapshot():
    app = create_app(ingest=False)
    with TestClient(app) as client:
        assert client.get("/tracks").json() == []
        # The app runs in another thread; the portal runs our coroutine on its loop.
        client.portal.call(feed, app, event(1), event(2))
        assert {t["mmsi"] for t in client.get("/tracks").json()} == {1, 2}
        assert client.get("/health").json()["tracks"] == 2


def test_live_sends_snapshot_then_updates():
    app = create_app(ingest=False)
    with TestClient(app) as client:
        client.portal.call(feed, app, event(1))
        with client.websocket_connect("/live") as ws:
            first = ws.receive_json()
            assert first["type"] == "snapshot"
            assert [t["mmsi"] for t in first["tracks"]] == [1]

            client.portal.call(feed, app, event(2))
            update = ws.receive_json()
            assert update["type"] == "track" and update["track"]["mmsi"] == 2


def test_area_is_null_without_ingestion():
    with TestClient(create_app(ingest=False)) as client:
        assert client.get("/area").json() is None


def test_history_endpoint():
    app = create_app(ingest=False)
    with TestClient(app) as client:
        client.portal.call(feed, app, event(1, 0))
        body = client.get("/tracks/1/history").json()
        assert body["mmsi"] == 1
        assert len(body["points"]) == 1
        assert body["stats"]["distance_nm"] == 0.0


def test_history_unknown_mmsi_is_404():
    with TestClient(create_app(ingest=False)) as client:
        assert client.get("/tracks/999/history").status_code == 404


def test_live_sends_stale_and_remove():
    app = create_app(ingest=False)
    with TestClient(app) as client:
        client.portal.call(feed, app, event(1))
        t0 = event(1).received_at
        with client.websocket_connect("/live") as ws:
            ws.receive_json()  # snapshot
            client.portal.call(feed, app, Tick(now=t0 + timedelta(minutes=10)))
            assert ws.receive_json() == {"type": "stale", "mmsi": 1}
            client.portal.call(feed, app, Tick(now=t0 + timedelta(minutes=60)))
            assert ws.receive_json() == {"type": "remove", "mmsi": 1}


ZONE = Zone(
    name="Z",
    kind="restricted",
    alert_on_entry=True,
    polygon=[(36.9, -8.1), (36.9, -7.9), (37.1, -7.9), (37.1, -8.1)],
)


def test_zones_endpoint():
    with TestClient(create_app(ingest=False, zones=[ZONE])) as client:
        zones = client.get("/zones").json()
        assert zones[0]["name"] == "Z"
        assert zones[0]["bbox"] == [[36.9, -8.1], [37.1, -7.9]]


def test_alert_on_live_and_in_alerts_endpoint():
    app = create_app(ingest=False, zones=[ZONE])
    with TestClient(app) as client:
        with client.websocket_connect("/live") as ws:
            assert ws.receive_json()["alerts"] == []  # snapshot
            client.portal.call(feed, app, event(1))  # at 37.0, -8.0: inside Z
            assert ws.receive_json()["type"] == "track"
            msg = ws.receive_json()
            assert msg["type"] == "alert" and msg["alert"]["kind"] == "enter"
        assert client.get("/alerts").json()[0]["zone"] == "Z"
        # A new client gets the alert in its snapshot.
        with client.websocket_connect("/live") as ws:
            assert len(ws.receive_json()["alerts"]) == 1


def test_coverage_gap_replaces_dark_alerts_end_to_end():
    app = create_app(ingest=False, zones=[ZONE])
    with TestClient(app) as client:
        # 5 ships inside zone Z, all silent at the same moment.
        client.portal.call(feed, app, *[event(m) for m in range(1, 6)])
        t0 = event(1).received_at
        for seconds in (600, 630, 660, 690, 720, 750):  # sweeps after 10 min
            client.portal.call(feed, app, Tick(now=t0 + timedelta(seconds=seconds)))
        kinds = [a["kind"] for a in client.get("/alerts").json()]
        assert kinds.count("coverage_lost") == 1
        assert "dark" not in kinds


def test_lone_ship_still_goes_dark_end_to_end():
    app = create_app(ingest=False, zones=[ZONE])
    with TestClient(app) as client:
        client.portal.call(feed, app, event(1))
        t0 = event(1).received_at
        for seconds in (600, 630, 660, 690, 720, 750):
            client.portal.call(feed, app, Tick(now=t0 + timedelta(seconds=seconds)))
        kinds = [a["kind"] for a in client.get("/alerts").json()]
        assert "dark" in kinds and "coverage_lost" not in kinds


def test_health_reports_pipeline_counters():
    app = create_app(ingest=False)
    with TestClient(app) as client:
        client.portal.call(feed, app, event(1, 0), event(1, 0))  # second is out of order
        health = client.get("/health").json()
        assert health["positions_accepted"] == 1
        assert health["rejected_out_of_order"] == 1
        assert health["frames_received"] == 0  # no aisstream in tests


def test_route_and_ships_need_a_database():
    with TestClient(create_app(ingest=False)) as client:
        assert client.get("/tracks/1/route").status_code == 503
        assert client.get("/ships").status_code == 503
        assert client.get("/tracks/1/route?hours=500").status_code == 422  # max 7 days


def test_simulated_sensor_end_to_end():
    """SensorTicks through the state task: a scripted dark target is confirmed,
    raises a dark_vessel alert, and appears on /live; the sweep is marked
    simulated and carries no ground truth."""
    from minicop.events import SensorTick

    app = create_app(ingest=False, zones=[], simulated_sensor=True)
    with TestClient(app) as client:
        sensor = app.state.runtime.sensor
        start = sensor.sim.start
        # Up to 3 simulated hours, one sweep every 30 s, until the alert fires.
        for k in range(1, 360):
            client.portal.call(feed, app, SensorTick(now=start + timedelta(seconds=30 * k)))
            if any(a["kind"] == "dark_vessel" for a in client.get("/alerts").json()):
                break
        alerts = [a for a in client.get("/alerts").json() if a["kind"] == "dark_vessel"]
        assert alerts and "SIMULATED" in alerts[0]["message"]
        assert alerts[0]["lat"] is not None
        with client.websocket_connect("/live") as ws:
            snap = ws.receive_json()
        assert snap["sensor"]["simulated"] is True
        assert all("truth" not in d for d in snap["sensor"]["detections"])
        assert any(d["confirmed"] for d in snap["dark"])


def test_simulated_sensor_is_off_by_default():
    app = create_app(ingest=False)
    with TestClient(app) as client:
        assert app.state.runtime.sensor is None
        with client.websocket_connect("/live") as ws:
            assert ws.receive_json()["dark"] == []


def test_demo_overrides_speed_up_only_the_drone():
    from minicop.api import apply_demo_overrides
    from minicop.sensors import load_sensors_config

    cfg = load_sensors_config()
    assert apply_demo_overrides(cfg, {}) is cfg
    fast = apply_demo_overrides(
        cfg, {"MINICOP_SENSOR_SWEEP_S": "1", "MINICOP_DRONE_SPEED_KN": "600"}
    )
    assert fast.drone.sweep_s == 1 and fast.drone.speed_kn == 600
    assert fast.dark_targets == cfg.dark_targets  # dark targets keep their real speed
