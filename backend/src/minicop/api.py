"""FastAPI app: wires ingestion -> state -> hub, and exposes the API.

Run from backend/:  uvicorn minicop.api:app
"""

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast

import asyncpg
from fastapi import FastAPI, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from minicop.alerts import Alert, AlertEngine, AlertKind
from minicop.anomalies import AnomalyConfig, AnomalyDetector, load_anomaly_config
from minicop.bathymetry import ACKNOWLEDGEMENT, Bathymetry, load_bathymetry
from minicop.config import Area, load_settings
from minicop.context import ContextMonitor, load_context_config
from minicop.coverage import CoverageConfig, CoverageMonitor, load_coverage_config
from minicop.events import (
    AnyEvent,
    SensorTick,
    StaticEvent,
    Tick,
    Track,
    ZoneAdded,
    ZoneRemoved,
)
from minicop.fusion import DarkTrack, FusionEngine
from minicop.history import HistoryPoint, HistoryStats
from minicop.history_db import HistoryDB, ShipSeen, window_start
from minicop.hub import Hub
from minicop.ingest import IngestStatus, run_ingestion
from minicop.ports import load_ports
from minicop.recorder import Recorder
from minicop.routes import MAX_POINTS, RoutePoint, RouteStats, route_stats, split_segments, thin
from minicop.sensors import DroneSimulator, SensorsConfig, load_sensors_config
from minicop.state import TrackStore
from minicop.user_zones import (
    UserZoneIn,
    delete_user_zone,
    load_user_zones,
    polygon_problem,
    save_user_zone,
)
from minicop.zones import Zone, load_zones

log = logging.getLogger(__name__)

EVENT_QUEUE_SIZE = 10_000
SWEEP_INTERVAL_S = 30

# Positions from ingestion and clock ticks share one queue (single writer).
EventQueue = asyncio.Queue[AnyEvent]


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
    sensor: "SimulatedSensor | None" = None,
    context: ContextMonitor | None = None,
) -> None:
    """The only task that mutates the store, the alert engine and the anomaly detector.
    Publishes every change to the hub."""

    def publish_alerts(alerts: list[Alert]) -> None:
        for alert in alerts:
            hub.publish({"type": "alert", "alert": alert.model_dump(mode="json")})

    while True:
        event = await events.get()
        try:
            if isinstance(event, StaticEvent):
                updated = store.apply_static(event)
                if updated is not None:
                    hub.publish({"type": "track", "track": updated.model_dump(mode="json")})
            elif isinstance(event, ZoneAdded):
                engine.add_zone(event.zone, store.snapshot())
                hub.publish({"type": "zones"})  # clients refetch GET /zones
            elif isinstance(event, ZoneRemoved):
                engine.remove_zone(event.name)
                hub.publish({"type": "zones"})
            elif isinstance(event, SensorTick):
                if sensor is not None:
                    for message in sensor.step(event.now, store, engine):
                        hub.publish(message)
            elif isinstance(event, Tick):
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
                    if context is not None:
                        context.on_removed(removed.mmsi)
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
                    if context is not None:
                        publish_alerts(context.on_track(track))
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


@dataclass
class SimulatedSensor:
    """The SIMULATED patrol drone and the AIS + sensor fusion (phase 15).
    Stepped by the state task (single writer) on every SensorTick."""

    sim: DroneSimulator
    fusion: FusionEngine
    sweep_s: float
    last_sweep: dict[str, object] | None = None  # public sweep, for /live snapshots
    dark: list[DarkTrack] = field(default_factory=list)
    # (contact id, area name) already alerted as dark_in_zone: once per visit.
    in_zone: set[tuple[str, str]] = field(default_factory=set)

    def step(
        self, now: datetime, store: TrackStore, engine: AlertEngine
    ) -> list[dict[str, object]]:
        tracks = store.snapshot()
        sweep = self.sim.sweep(now, tracks)
        outcome = self.fusion.process(sweep, tracks)
        messages: list[dict[str, object]] = []
        for mmsi, t in outcome.fused.items():
            updated = store.mark_sensor(mmsi, t)
            if updated is not None:
                messages.append({"type": "track", "track": updated.model_dump(mode="json")})
        # The ground truth of each detection is for evaluation only: not published.
        self.last_sweep = {
            "simulated": True,
            **sweep.model_dump(mode="json", exclude={"detections": {"__all__": {"truth"}}}),
        }
        self.dark = outcome.dark
        messages.append({"type": "sensor", "sweep": self.last_sweep})
        messages.append({"type": "dark", "tracks": [d.model_dump(mode="json") for d in self.dark]})
        for d in outcome.newly_confirmed:
            stand_in = _stand_in(d)
            motion = (
                f"~{d.sog:.0f} kn heading {d.cog:.0f}°"
                if d.sog is not None and d.cog is not None
                else "speed not yet known"
            )
            alert = engine.record(
                AlertKind.DARK_VESSEL,
                stand_in,
                d.last_seen,
                f"Non-cooperative contact {d.id}: {d.detections} sensor detections, no AIS, "
                f"{motion} (SIMULATED sensor)",
                lat=d.lat,
                lon=d.lon,
            )
            messages.append({"type": "alert", "alert": alert.model_dump(mode="json")})
        messages.extend(self._dark_in_zones(engine))
        return messages

    def _dark_in_zones(self, engine: AlertEngine) -> list[dict[str, object]]:
        """Phase 16: one alert per dark contact and area it is in (not for
        contacts an AIS ship could explain). Leaving the area re-arms it."""
        messages: list[dict[str, object]] = []
        now_in: set[tuple[str, str]] = set()
        for d in self.dark:
            if not d.confirmed or d.possible_mmsi is not None:
                continue
            for zone in engine.zones_containing(d.lat, d.lon):
                key = (d.id, zone.name)
                now_in.add(key)
                if key in self.in_zone:
                    continue
                alert = engine.record(
                    AlertKind.DARK_IN_ZONE,
                    _stand_in(d),
                    d.last_seen,
                    f"Non-cooperative contact {d.id} inside {zone.name} (SIMULATED sensor)",
                    zone=zone.name,
                    lat=d.lat,
                    lon=d.lon,
                )
                messages.append({"type": "alert", "alert": alert.model_dump(mode="json")})
        self.in_zone = now_in
        return messages


def _stand_in(d: DarkTrack) -> Track:
    """Alerts are keyed by ship; a dark contact has no MMSI (0) and its id as name."""
    return Track(
        mmsi=0,
        ship_name=d.id,
        latitude=d.lat,
        longitude=d.lon,
        sog=d.sog or 0.0,
        cog=d.cog if d.cog is not None else 360.0,  # 360 = "not available"
        true_heading=511,
        navigational_status=15,
        last_seen=d.last_seen,
    )


async def run_sensor_clock(events: EventQueue, sweep_s: float) -> None:
    """Puts a SensorTick on the event queue every sweep."""
    while True:
        await asyncio.sleep(sweep_s)
        await events.put(SensorTick(now=datetime.now(UTC)))


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
    context: ContextMonitor
    recorder: Recorder | None  # None when DATABASE_URL is not set
    history_db: HistoryDB | None  # read side of the recorded history (phase 14)
    sensor: SimulatedSensor | None  # SIMULATED drone + fusion (phase 15), off by default
    status: IngestStatus
    area: Area | None
    # Names of the areas drawn by operators (phase 16). Kept here, under
    # zone_lock, so the API can check names without waiting for the state task.
    user_zone_names: set[str] = field(default_factory=set)
    zone_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ZoneCreated(BaseModel):
    zone: Zone
    saved: bool  # False without a database: the area is lost on restart


async def load_saved_zones(rt: Runtime) -> None:
    """Put the areas saved in the database on the queue, once the recorder has
    connected (it runs the migrations, including 003_user_zones). Retries
    quietly while the database is down."""
    if rt.recorder is None or rt.history_db is None:
        return
    while True:
        if rt.recorder.connected:
            try:
                zones = await load_user_zones(await rt.history_db.pool())
            except (OSError, asyncpg.PostgresError) as exc:
                log.warning("Could not load drawn areas yet: %s", exc)
            else:
                async with rt.zone_lock:
                    for zone in zones:
                        if zone.name not in rt.user_zone_names:
                            rt.user_zone_names.add(zone.name)
                            await rt.events.put(ZoneAdded(zone=zone))
                log.info("Loaded %d drawn areas", len(zones))
                return
        await asyncio.sleep(2)


def apply_demo_overrides(cfg: SensorsConfig, env: Mapping[str, str]) -> SensorsConfig:
    """Optional overrides to watch the simulation without waiting:
    MINICOP_SENSOR_SWEEP_S (seconds between sweeps, config: 30) and
    MINICOP_DRONE_SPEED_KN (config: 60 kn, one patrol loop in ~77 min).
    Only the drone is sped up; the scripted dark targets keep their real speed,
    so the fusion's plausible-speed check still applies to them."""
    drone: dict[str, float] = {}
    if env.get("MINICOP_SENSOR_SWEEP_S", "").strip():
        drone["sweep_s"] = float(env["MINICOP_SENSOR_SWEEP_S"])
    if env.get("MINICOP_DRONE_SPEED_KN", "").strip():
        drone["speed_kn"] = float(env["MINICOP_DRONE_SPEED_KN"])
    if not drone:
        return cfg
    return cfg.model_copy(update={"drone": cfg.drone.model_copy(update=drone)})


def _simulated_sensor(enabled: bool | None, cfg: SensorsConfig | None) -> SimulatedSensor | None:
    """The simulated sensor is OFF unless asked for (MINICOP_SIMULATED_SENSOR=1),
    so simulated contacts are never mixed into a picture by accident."""
    if enabled is None:
        enabled = os.getenv("MINICOP_SIMULATED_SENSOR", "0").strip() == "1"
    if not enabled:
        return None
    cfg = apply_demo_overrides(cfg or load_sensors_config(), os.environ)
    return SimulatedSensor(
        sim=DroneSimulator(cfg, start=datetime.now(UTC)),
        fusion=FusionEngine(cfg.fusion),
        sweep_s=cfg.drone.sweep_s,
    )


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
    simulated_sensor: bool | None = None,
    sensors_config: SensorsConfig | None = None,
    bathymetry: Bathymetry | None | bool = True,
) -> FastAPI:
    """ingest=False skips aisstream (and the API key); tests feed
    app.state.runtime.events. zones defaults to config/zones.toml; tests pass their own."""
    # Alert zones from zones.toml, plus port areas from OpenStreetMap (ports.json).
    zone_list = load_zones() + load_ports() if zones is None else zones
    # Phase 17a: bathymetry for the configured area (True = load the file for
    # MINICOP_AREA if it exists; tests pass a Bathymetry, or None for none).
    if bathymetry is True:
        area_name = os.getenv("MINICOP_AREA", "algarve").strip()
        bathy = load_bathymetry(area_name)
        if bathy is None:
            log.warning(
                "No bathymetry for area '%s': depth and impossible-position checks are off. "
                "Run: python scripts/fetch_bathymetry.py --area %s",
                area_name,
                area_name,
            )
    else:
        bathy = bathymetry or None
    context_cfg = load_context_config()
    anomaly_cfg = load_anomaly_config() if anomaly_config is None else anomaly_config
    coverage_cfg = load_coverage_config() if coverage_config is None else coverage_config

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = load_settings() if ingest else None  # fails fast if the API key is missing
        alert_engine = AlertEngine(zone_list)
        rt = Runtime(
            events=asyncio.Queue(maxsize=EVENT_QUEUE_SIZE),
            store=TrackStore(bathy),
            hub=Hub(),
            alerts=alert_engine,
            anomalies=AnomalyDetector(anomaly_cfg, zone_list, alert_engine),
            coverage=CoverageMonitor(coverage_cfg, alert_engine),
            context=ContextMonitor(context_cfg, bathy, zone_list, alert_engine),
            recorder=_recorder_from_env(),
            history_db=_history_db_from_env(),
            sensor=_simulated_sensor(simulated_sensor, sensors_config),
            status=IngestStatus(),
            area=settings.area if settings else None,
        )
        app.state.runtime = rt
        tasks = [
            asyncio.create_task(
                run_state(
                    rt.events,
                    rt.store,
                    rt.alerts,
                    rt.anomalies,
                    rt.coverage,
                    rt.hub,
                    rt.recorder,
                    rt.sensor,
                    rt.context,
                )
            ),
            asyncio.create_task(run_clock(rt.events)),
            *(
                [asyncio.create_task(run_sensor_clock(rt.events, rt.sensor.sweep_s))]
                if rt.sensor is not None
                else []
            ),
        ]
        if rt.recorder is not None:
            tasks.append(asyncio.create_task(rt.recorder.run()))
            tasks.append(asyncio.create_task(load_saved_zones(rt)))
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
            "static_frames": rt.status.statics,
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

    shading_cache: dict[int, bytes] = {}

    @app.get("/bathymetry")
    async def bathymetry_info() -> dict[str, object]:
        """Phase 17a: whether depth data is loaded, its bounds and attribution."""
        if bathy is None:
            return {"available": False}
        return {"available": True, "attribution": ACKNOWLEDGEMENT, "grids": bathy.grids()}

    @app.get("/bathymetry/{index}.png")
    async def bathymetry_png(index: int) -> Response:
        """Depth shading for the map (computed once per grid, then cached)."""
        if bathy is None or not 0 <= index < len(bathy.grids()):
            raise HTTPException(404, "No such bathymetry grid")
        if index not in shading_cache:
            shading_cache[index] = bathy.shading_png(index)
        return Response(shading_cache[index], media_type="image/png")

    @app.get("/zones")
    async def zones_() -> list[Zone]:
        """Config zones, ports and the areas drawn by operators (`source`)."""
        return runtime().alerts.zones

    fixed_names = {z.name for z in zone_list}

    @app.post("/zones", status_code=201)
    async def create_zone(body: UserZoneIn) -> ZoneCreated:
        """An operator drew an area (phase 16). Stored when there is a database."""
        rt = runtime()
        zone = body.to_zone()
        problem = polygon_problem(zone.polygon, rt.area)
        if problem:
            raise HTTPException(422, problem)
        async with rt.zone_lock:
            if zone.name in fixed_names or zone.name in rt.user_zone_names:
                raise HTTPException(409, f'An area called "{zone.name}" already exists')
            saved = False
            if rt.history_db is not None:
                try:
                    await save_user_zone(await rt.history_db.pool(), zone)
                except (OSError, asyncpg.PostgresError) as exc:
                    raise HTTPException(
                        503, f"Area not saved, database unavailable: {exc}"
                    ) from exc
                saved = True
            rt.user_zone_names.add(zone.name)
            await rt.events.put(ZoneAdded(zone=zone))
        return ZoneCreated(zone=zone, saved=saved)

    @app.delete("/zones/{name}", status_code=204)
    async def delete_zone(name: str) -> None:
        """Delete a drawn area. Config zones and ports can't be deleted."""
        rt = runtime()
        async with rt.zone_lock:
            if name in fixed_names:
                raise HTTPException(409, "Only areas drawn on the map can be deleted")
            if name not in rt.user_zone_names:
                raise HTTPException(404, f'No drawn area called "{name}"')
            if rt.history_db is not None:
                try:
                    await delete_user_zone(await rt.history_db.pool(), name)
                except (OSError, asyncpg.PostgresError) as exc:
                    raise HTTPException(503, f"Database unavailable: {exc}") from exc
            rt.user_zone_names.discard(name)
            await rt.events.put(ZoneRemoved(name=name))

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
            "sensor": rt.sensor.last_sweep if rt.sensor else None,
            "dark": [d.model_dump(mode="json") for d in rt.sensor.dark] if rt.sensor else [],
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
