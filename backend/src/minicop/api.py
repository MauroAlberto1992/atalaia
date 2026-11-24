"""FastAPI app: wires ingestion -> state -> hub, and exposes the API.

Run from backend/:  uvicorn minicop.api:app
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from minicop.alerts import Alert, AlertEngine
from minicop.config import Area, load_settings
from minicop.events import PositionEvent, Tick, Track
from minicop.history import HistoryPoint, HistoryStats
from minicop.hub import Hub
from minicop.ingest import IngestStatus, run_ingestion
from minicop.state import TrackStore
from minicop.zones import Zone, load_zones

log = logging.getLogger(__name__)

EVENT_QUEUE_SIZE = 10_000
SWEEP_INTERVAL_S = 30


class HistoryResponse(BaseModel):
    mmsi: int
    points: list[HistoryPoint]
    stats: HistoryStats


async def run_state(
    events: asyncio.Queue[PositionEvent | Tick], store: TrackStore, engine: AlertEngine, hub: Hub
) -> None:
    """The only task that mutates the store and the alert engine.
    Publishes every change to the hub."""

    def publish_alerts(alerts: list[Alert]) -> None:
        for alert in alerts:
            hub.publish({"type": "alert", "alert": alert.model_dump(mode="json")})

    while True:
        event = await events.get()
        try:
            if isinstance(event, Tick):
                result = store.sweep(event.now)
                for mmsi in result.stale:
                    hub.publish({"type": "stale", "mmsi": mmsi})
                    track = store.get(mmsi)
                    if track is not None:
                        publish_alerts(engine.on_stale(track, event.now))
                for mmsi in result.removed:
                    engine.on_removed(mmsi)
                    hub.publish({"type": "remove", "mmsi": mmsi})
            else:
                track = store.apply(event)
                if track is not None:
                    # Track first, then its alerts: the client knows the ship
                    # by the time it shows an alert about it.
                    hub.publish({"type": "track", "track": track.model_dump(mode="json")})
                    publish_alerts(engine.on_track(track))
        finally:
            events.task_done()  # lets tests await events.join()


async def run_clock(events: asyncio.Queue[PositionEvent | Tick]) -> None:
    """Puts a Tick on the event queue every SWEEP_INTERVAL_S."""
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_S)
        await events.put(Tick(now=datetime.now(timezone.utc)))


def create_app(ingest: bool = True, zones: list[Zone] | None = None) -> FastAPI:
    """ingest=False skips aisstream (and the API key); tests feed app.state.events.
    zones defaults to config/zones.toml; tests pass their own."""
    zone_list = load_zones() if zones is None else zones

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.events = asyncio.Queue(maxsize=EVENT_QUEUE_SIZE)
        app.state.store = TrackStore()
        app.state.hub = Hub()
        app.state.alerts = AlertEngine(zone_list)
        app.state.status = IngestStatus()
        tasks = [
            asyncio.create_task(run_state(app.state.events, app.state.store, app.state.alerts, app.state.hub)),
            asyncio.create_task(run_clock(app.state.events)),
        ]
        app.state.area = None
        if ingest:
            settings = load_settings()  # fails fast if the API key is missing
            app.state.area = settings.area
            tasks.append(asyncio.create_task(
                run_ingestion(settings, app.state.events, app.state.status)
            ))
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="Mini-COP", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {
            "aisstream_connected": app.state.status.connected,
            "last_message_at": app.state.status.last_message_at,
            "reconnects": app.state.status.reconnects,
            "tracks": len(app.state.store),
            "live_clients": len(app.state.hub),
        }

    @app.get("/area")
    async def area() -> Area | None:
        """The configured area, so the map can frame it without hard-coding it."""
        return app.state.area

    @app.get("/zones")
    async def zones_() -> list[Zone]:
        return zone_list

    @app.get("/alerts")
    async def alerts() -> list[Alert]:
        """Most recent alerts (up to 200), newest first."""
        return app.state.alerts.recent()

    @app.get("/tracks")
    async def tracks() -> list[Track]:
        return app.state.store.snapshot()

    @app.get("/tracks/{mmsi}/history")
    async def history(mmsi: int) -> HistoryResponse:
        h = app.state.store.history(mmsi)
        if h is None:
            raise HTTPException(status_code=404, detail="Unknown MMSI")
        return HistoryResponse(mmsi=mmsi, points=h.points(), stats=h.stats())

    @app.websocket("/live")
    async def live(ws: WebSocket) -> None:
        await ws.accept()
        # Subscribe and take the snapshot with no await in between: both run in
        # one step of the event loop, so no update can fall into a gap.
        queue = app.state.hub.subscribe()
        snapshot = {
            "type": "snapshot",
            "tracks": [t.model_dump(mode="json") for t in app.state.store.snapshot()],
            "alerts": [a.model_dump(mode="json") for a in app.state.alerts.recent()],
        }
        try:
            await ws.send_json(snapshot)
            while (message := await queue.get()) is not None:
                await ws.send_json(message)
            await ws.close(code=1013)  # dropped as slow client: "try again later"
        except WebSocketDisconnect:
            pass
        finally:
            app.state.hub.unsubscribe(queue)

    return app


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
app = create_app()
