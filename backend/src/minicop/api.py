"""FastAPI app: wires ingestion -> state -> hub, and exposes the API.

Run from backend/:  uvicorn minicop.api:app
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from minicop.config import Area, load_settings
from minicop.events import PositionEvent, Track
from minicop.history import HistoryPoint, HistoryStats
from minicop.hub import Hub
from minicop.ingest import IngestStatus, run_ingestion
from minicop.state import TrackStore

log = logging.getLogger(__name__)

EVENT_QUEUE_SIZE = 10_000


class HistoryResponse(BaseModel):
    mmsi: int
    points: list[HistoryPoint]
    stats: HistoryStats


async def run_state(events: asyncio.Queue[PositionEvent], store: TrackStore, hub: Hub) -> None:
    """The only task that mutates the store. Publishes every change to the hub."""
    while True:
        event = await events.get()
        try:
            track = store.apply(event)
            if track is not None:
                hub.publish({"type": "track", "track": track.model_dump(mode="json")})
        finally:
            events.task_done()  # lets tests await events.join()


def create_app(ingest: bool = True) -> FastAPI:
    """ingest=False skips aisstream (and the API key); tests feed app.state.events."""

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.events = asyncio.Queue(maxsize=EVENT_QUEUE_SIZE)
        app.state.store = TrackStore()
        app.state.hub = Hub()
        app.state.status = IngestStatus()
        tasks = [asyncio.create_task(run_state(app.state.events, app.state.store, app.state.hub))]
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
            "tracks": len(app.state.store),
            "live_clients": len(app.state.hub),
        }

    @app.get("/area")
    async def area() -> Area | None:
        """The configured area, so the map can frame it without hard-coding it."""
        return app.state.area

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
        snapshot = [t.model_dump(mode="json") for t in app.state.store.snapshot()]
        try:
            await ws.send_json({"type": "snapshot", "tracks": snapshot})
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
