"""Regression tests for the review of the real-time core (state task, API,
bathymetry edges, static data). Each one failed on the code before the fix."""

import asyncio
import time
from datetime import UTC, datetime, timedelta

import httpx
from fastapi.testclient import TestClient

from minicop import state as state_module
from minicop.api import _bathymetry_for, create_app
from minicop.bathymetry import load_bathymetry
from minicop.events import PositionEvent, StaticEvent
from minicop.state import TrackStore

B = load_bathymetry("algarve")
T0 = datetime(2026, 11, 28, 10, 0, tzinfo=UTC)
SHALLOW_8M = (37.1891, -7.2672)  # from the grid (see test_context.py)


def position(mmsi: int, lat: float = 36.95, lon: float = -8.53, t: datetime = T0) -> PositionEvent:
    return PositionEvent(
        mmsi=mmsi,
        latitude=lat,
        longitude=lon,
        sog=9.0,
        cog=90.0,
        true_heading=511,
        navigational_status=0,
        ship_name=f"S{mmsi}",
        received_at=t,
    )


async def feed(app, *events) -> None:
    for e in events:
        await app.state.runtime.events.put(e)
    await app.state.runtime.events.join()


def test_state_task_survives_an_error_in_one_event():
    app = create_app(ingest=False, zones=[], bathymetry=None)
    with TestClient(app) as client:
        rt = app.state.runtime
        real = rt.alerts.on_track
        calls = {"n": 0}

        def flaky(track):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return real(track)

        rt.alerts.on_track = flaky
        client.portal.call(feed, app, position(1), position(2))
        assert {t["mmsi"] for t in client.get("/tracks").json()} == {1, 2}  # 2 still processed
        assert client.get("/health").json()["state_errors"] == 1


def test_shading_runs_off_the_event_loop_and_once():
    app = create_app(ingest=False, zones=[], bathymetry=B)
    with TestClient(app) as client:
        bathy = app.state.runtime.bathymetry
        computed = {"n": 0}

        def slow_png(index: int) -> bytes:
            computed["n"] += 1
            time.sleep(0.3)  # stands in for a whole-coast grid
            return b"\x89PNG fake"

        bathy.shading_png = slow_png

        async def scenario() -> int:
            ticks = 0

            async def ticker() -> None:
                nonlocal ticks
                while True:
                    await asyncio.sleep(0.01)
                    ticks += 1

            t = asyncio.create_task(ticker())
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://x") as ac:
                await asyncio.gather(ac.get("/bathymetry/0.png"), ac.get("/bathymetry/0.png"))
            t.cancel()
            return ticks

        ticks = client.portal.call(scenario)
        assert computed["n"] == 1  # two first requests, one computation
        assert ticks >= 10  # the loop kept running during the 0.3 s


def test_bathymetry_follows_the_configured_area_name():
    assert _bathymetry_for("algarve") is not None
    assert _bathymetry_for("no-such-area") is None


def test_point_just_north_or_west_of_the_grid_is_outside():
    assert B is not None
    north = B.grids()[0]["north"]
    west = B.grids()[0]["west"]
    assert not B.covers(north + 0.0005, -8.5)  # ~55 m north of the grid
    assert not B.covers(37.0, west - 0.0005)
    assert B.depth_m(north + 0.0005, -8.5) is None


def test_full_queue_refuses_area_changes_instead_of_hanging():
    app = create_app(ingest=False, zones=[], bathymetry=None)
    with TestClient(app) as client:
        rt = app.state.runtime

        def full(_event):
            raise asyncio.QueueFull

        rt.events.put_nowait = full
        box = [[36.9, -8.5], [36.9, -8.4], [36.81, -8.45]]
        r = client.post("/zones", json={"name": "Busy", "kind": "watch", "polygon": box})
        assert r.status_code == 503
        assert "Busy" not in rt.user_zone_names  # not half-created


def test_draught_arriving_after_the_position_is_checked_at_once():
    app = create_app(ingest=False, zones=[], bathymetry=B)
    with TestClient(app) as client:
        client.portal.call(feed, app, position(7, *SHALLOW_8M))
        assert client.get("/alerts").json() == []  # no draught yet: can't tell
        client.portal.call(feed, app, StaticEvent(mmsi=7, ship_type=70, draught_m=10.6))
        assert [a["kind"] for a in client.get("/alerts").json()] == ["impossible_position"]


def test_evicted_static_data_is_not_wiped_from_a_live_track(monkeypatch):
    monkeypatch.setattr(state_module, "MAX_STATIC", 2)
    store = TrackStore(None)
    store.apply(position(1))
    store.apply_static(StaticEvent(mmsi=1, ship_type=70, draught_m=10.6))
    store.apply_static(StaticEvent(mmsi=2, ship_type=30))
    store.apply_static(StaticEvent(mmsi=3, ship_type=30))  # evicts ship 1's entry
    track = store.apply(position(1, t=T0 + timedelta(minutes=1)))
    assert track is not None and track.ship_type == 70 and track.draught_m == 10.6
