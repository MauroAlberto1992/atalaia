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
