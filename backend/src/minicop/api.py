"""FastAPI app: wires ingestion -> state -> hub, and exposes the API.

Run from backend/:  uvicorn minicop.api:app
"""

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import asyncpg
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from minicop.alerts import Alert, AlertEngine
from minicop.anomalies import AnomalyConfig, AnomalyDetector, load_anomaly_config
from minicop.config import Area, load_settings
from minicop.coverage import CoverageConfig, CoverageMonitor, load_coverage_config
from minicop.events import PositionEvent, Tick, Track
from minicop.history import HistoryPoint, HistoryStats
from minicop.history_db import HistoryDB, ShipSeen, window_start
from minicop.hub import Hub
from minicop.ingest import IngestStatus, run_ingestion
from minicop.ports import load_ports
from minicop.recorder import Recorder
from minicop.routes import MAX_POINTS, RoutePoint, RouteStats, route_stats, split_segments, thin
from minicop.state import TrackStore
from minicop.zones import Zone, load_zones

log = logging.getLogger(__name__)

EVENT_QUEUE_SIZE = 10_000
SWEEP_INTERVAL_S = 30

# Positions from ingestion and clock ticks share one queue (single writer).
EventQueue = asyncio.Queue[PositionEvent | Tick]


class RouteResponse(BaseModel):
    mmsi: int
    hours: int
    thinned: bool  # True if more than MAX_POINTS points were evenly thinned
    segments: list[list[RoutePoint]]  # split where points are > 30 min apart
    stats: RouteStats


class HistoryResponse(BaseModel):
    mmsi: int
    points: list[HistoryPoint]
    stats: HistoryStats


async def run_state(
    events: EventQueue,
    store: TrackStore,
    engine: AlertEngine,
    anomalies: AnomalyDetector,
    coverage: CoverageMonitor,
    hub: Hub,
    recorder: Recorder | None = None,
) -> None:
    """The only task that mutates the store, the alert engine and the anomaly detector.
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
                    hub.publish({"type": "stale", "mmsi": mmsi})  # map greys it now
                    track = store.get(mmsi)
                    if track is not None:
                        coverage.add_stale(track, event.now)
                # Coverage gaps first; "dark" alerts only for ships that went
                # silent on their own (released after the cohort window).
                gap_alerts, released = coverage.process(event.now)
                publish_alerts(gap_alerts)
                for silent in released:
                    current = store.get(silent.mmsi)
                    if current is not None and current.stale:
                        publish_alerts(engine.on_stale(current, event.now))
                for removed in result.removed_tracks:
                    engine.on_removed(removed.mmsi)
                    anomalies.on_removed(removed)
                    hub.publish({"type": "remove", "mmsi": removed.mmsi})
                anomalies.on_tick(event.now)
                coverage.on_tick(event.now)
            else:
                track = store.apply(event)
                if track is not None:
                    # Track first, then its alerts: the client knows the ship
                    # by the time it shows an alert about it.
                    hub.publish({"type": "track", "track": track.model_dump(mode="json")})
                    if recorder is not None:
                        recorder.enqueue(track)  # never waits (see recorder.py)
                    publish_alerts(engine.on_track(track))
                    restored, in_gap = coverage.on_track(track)
                    publish_alerts(restored)
                    publish_alerts(
                        anomalies.on_track(
                            track, store.history(track.mmsi), silence_was_coverage=in_gap
                        )
                    )
                # Every report, accepted or rejected, can count towards spoofing.
                window = timedelta(minutes=anomalies.cfg.spoof_window_min)
                jumps = store.jumps_since(event.mmsi, event.received_at - window)
                publish_alerts(anomalies.on_position(event, jumps))
        finally:
            events.task_done()  # lets tests await events.join()


async def run_clock(events: EventQueue) -> None:
    """Puts a Tick on the event queue every SWEEP_INTERVAL_S."""
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_S)
        await events.put(Tick(now=datetime.now(UTC)))


@dataclass
class Runtime:
    """Everything the running service holds, created in the lifespan.

    Kept in one typed object instead of loose attributes on app.state
    (which Starlette types as Any), so mypy checks every use.
    """

    events: EventQueue
    store: TrackStore
    hub: Hub
    alerts: AlertEngine
    anomalies: AnomalyDetector
    coverage: CoverageMonitor
    recorder: Recorder | None  # None when DATABASE_URL is not set
    history_db: HistoryDB | None  # read side of the recorded history (phase 14)
    status: IngestStatus
    area: Area | None


def _history_db_from_env() -> HistoryDB | None:
    dsn = os.getenv("DATABASE_URL", "").strip()
    return HistoryDB(dsn) if dsn else None


def _recorder_from_env() -> Recorder | None:
    """Recording is optional: without DATABASE_URL everything works as before
    (development without Docker, unit tests)."""
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        return None
    return Recorder(dsn, retention_days=int(os.getenv("MINICOP_RETENTION_DAYS", "30")))


def _recorder_health(recorder: Recorder | None) -> dict[str, object]:
    if recorder is None:
        return {"db_enabled": False}
    return {
        "db_enabled": True,
        "db_connected": recorder.connected,
        "db_written": recorder.written,
        "db_queued": len(recorder.buffer),
        "db_dropped": recorder.buffer.dropped,
    }


def create_app(
    ingest: bool = True,
    zones: list[Zone] | None = None,
    anomaly_config: AnomalyConfig | None = None,
    coverage_config: CoverageConfig | None = None,
) -> FastAPI:
    """ingest=False skips aisstream (and the API key); tests feed
    app.state.runtime.events. zones defaults to config/zones.toml; tests pass their own."""
    # Alert zones from zones.toml, plus port areas from OpenStreetMap (ports.json).
    zone_list = load_zones() + load_ports() if zones is None else zones
    anomaly_cfg = load_anomaly_config() if anomaly_config is None else anomaly_config
    coverage_cfg = load_coverage_config() if coverage_config is None else coverage_config

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = load_settings() if ingest else None  # fails fast if the API key is missing
        alert_engine = AlertEngine(zone_list)
        rt = Runtime(
            events=asyncio.Queue(maxsize=EVENT_QUEUE_SIZE),
            store=TrackStore(),
            hub=Hub(),
            alerts=alert_engine,
            anomalies=AnomalyDetector(anomaly_cfg, zone_list, alert_engine),
            coverage=CoverageMonitor(coverage_cfg, alert_engine),
            recorder=_recorder_from_env(),
            history_db=_history_db_from_env(),
            status=IngestStatus(),
            area=settings.area if settings else None,
        )
        app.state.runtime = rt
        tasks = [
            asyncio.create_task(
                run_state(
                    rt.events, rt.store, rt.alerts, rt.anomalies, rt.coverage, rt.hub, rt.recorder
                )
            ),
            asyncio.create_task(run_clock(rt.events)),
        ]
        if rt.recorder is not None:
            tasks.append(asyncio.create_task(rt.recorder.run()))
        if settings:
            tasks.append(asyncio.create_task(run_ingestion(settings, rt.events, rt.status)))
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if rt.history_db is not None:
            await rt.history_db.close()

    app = FastAPI(title="Mini-COP", lifespan=lifespan)

    def runtime() -> Runtime:
        return cast(Runtime, app.state.runtime)

    @app.get("/health")
    async def health() -> dict[str, object]:
        rt = runtime()
        return {
            "aisstream_connected": rt.status.connected,
            "last_message_at": rt.status.last_message_at,
            "reconnects": rt.status.reconnects,
            # Pipeline: frames from aisstream -> usable positions -> accepted
            # by the state (the rest: out of order or impossible jumps).
            "frames_received": rt.status.frames,
            "positions_parsed": rt.status.positions,
            "positions_class_a": rt.status.positions_by_class["A"],
            "positions_class_b": rt.status.positions_by_class["B"],
            "positions_accepted": rt.store.accepted,
            "rejected_out_of_order": rt.store.out_of_order,
            "rejected_jumps": rt.store.jumps_rejected,
            "tracks": len(rt.store),
            "live_clients": len(rt.hub),
            **_recorder_health(rt.recorder),
        }

    @app.get("/area")
    async def area() -> Area | None:
        """The configured area, so the map can frame it without hard-coding it."""
        return runtime().area

    @app.get("/zones")
    async def zones_() -> list[Zone]:
        return zone_list

    @app.get("/alerts")
    async def alerts() -> list[Alert]:
        """Most recent alerts (up to 200), newest first."""
        return runtime().alerts.recent()

    @app.get("/tracks")
    async def tracks() -> list[Track]:
        return runtime().store.snapshot()

    def history_db() -> HistoryDB:
        db = runtime().history_db
        if db is None:
            raise HTTPException(503, "No database configured (DATABASE_URL); live history only")
        return db

    @app.get("/tracks/{mmsi}/route")
    async def route(mmsi: int, hours: int = Query(24, ge=1, le=168)) -> RouteResponse:
        """Recorded route of one ship over the last `hours`, split at gaps."""
        try:
            points = await history_db().route(mmsi, window_start(datetime.now(UTC), hours))
        except (OSError, asyncpg.PostgresError) as exc:
            raise HTTPException(503, f"Database unavailable: {exc}") from exc
        points, thinned = thin(points, MAX_POINTS)
        segments = split_segments(points)
        return RouteResponse(
            mmsi=mmsi,
            hours=hours,
            thinned=thinned,
            segments=segments,
            stats=route_stats(segments),
        )

    @app.get("/ships")
    async def ships(hours: int = Query(24, ge=1, le=168)) -> list[ShipSeen]:
        """Ships recorded in the last `hours`, including ones no longer live."""
        try:
            return await history_db().ships(window_start(datetime.now(UTC), hours))
        except (OSError, asyncpg.PostgresError) as exc:
            raise HTTPException(503, f"Database unavailable: {exc}") from exc

    @app.get("/tracks/{mmsi}/history")
    async def history(mmsi: int) -> HistoryResponse:
        h = runtime().store.history(mmsi)
        if h is None:
            raise HTTPException(status_code=404, detail="Unknown MMSI")
        return HistoryResponse(mmsi=mmsi, points=h.points(), stats=h.stats())

    @app.websocket("/live")
    async def live(ws: WebSocket) -> None:
        rt = runtime()
        await ws.accept()
        # Subscribe and take the snapshot with no await in between: both run in
        # one step of the event loop, so no update can fall into a gap.
        queue = rt.hub.subscribe()
        snapshot = {
            "type": "snapshot",
            "tracks": [t.model_dump(mode="json") for t in rt.store.snapshot()],
            "alerts": [a.model_dump(mode="json") for a in rt.alerts.recent()],
        }
        try:
            await ws.send_json(snapshot)
            while (message := await queue.get()) is not None:
                await ws.send_json(message)
            await ws.close(code=1013)  # dropped as slow client: "try again later"
        except WebSocketDisconnect:
            pass
        finally:
            rt.hub.unsubscribe(queue)

    return app


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
app = create_app()
