"""API tests with fake events: no aisstream, no API key."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from minicop.api import create_app
from minicop.events import PositionEvent


def event(mmsi: int, second: int = 0) -> PositionEvent:
    return PositionEvent(
        mmsi=mmsi, latitude=37.0, longitude=-8.0, sog=5.0, cog=0.0, true_heading=0,
        navigational_status=0, ship_name="TEST",
        received_at=datetime(2026, 11, 24, 12, 0, second, tzinfo=timezone.utc),
    )


async def feed(app, *events: PositionEvent) -> None:
    """Put events on the queue and wait until the state task has applied them."""
    for e in events:
        await app.state.events.put(e)
    await app.state.events.join()


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
