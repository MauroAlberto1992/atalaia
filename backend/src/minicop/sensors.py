"""SIMULATED non-cooperative sensor (phase 15). Not real data.

A patrol drone flies a loop; every sweep it reports detections inside its
footprint: real AIS ships (with probability Pd and position noise), scripted
"dark" targets that never transmit AIS, and random clutter.

Each detection carries its ground truth (`truth`) so the fusion can be
*measured*. The fusion itself never reads `truth`.

Why the simulator runs inside the state task: to detect real AIS ships it needs
their true positions, which only the state holds. A real sensor would be a
separate ingestion task producing the same `Detection` objects; the fusion code
would not change.
"""

import math
import random
import tomllib
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from minicop.config import BACKEND_DIR, Corner
from minicop.events import Track
from minicop.geo import haversine_nm

DEFAULT_SENSORS_FILE = BACKEND_DIR / "config" / "sensors.toml"


class DroneConfig(BaseModel):
    id: str
    speed_kn: float
    footprint_nm: float
    sweep_s: float
    pd: float
    position_sigma_m: float
    false_alarms_per_sweep: float
    seed: int
    patrol: list[Corner]


class DarkTargetConfig(BaseModel):
    name: str
    speed_kn: float
    loop: bool = True
    path: list[Corner]


class FusionConfig(BaseModel):
    track_max_age_min: float
    gate_nm: float
    gate_growth_nm_per_min: float
    gate_max_nm: float
    confirm_hits: int
    confirm_window: int
    candidate_gate_nm: float
    max_speed_kn: float
    drop_after_min: float


class SensorsConfig(BaseModel):
    drone: DroneConfig
    dark_targets: list[DarkTargetConfig] = []
    fusion: FusionConfig


def load_sensors_config(path: Path = DEFAULT_SENSORS_FILE) -> SensorsConfig:
    with path.open("rb") as f:
        return SensorsConfig(**tomllib.load(f))


class Detection(BaseModel):
    """One sensor detection: something is here, identity unknown."""

    time: datetime
    lat: float
    lon: float
    sigma_m: float
    sensor_id: str
    # SIMULATION ONLY: what really caused it ("ais:<mmsi>", "dark:<name>",
    # "clutter"). Used by the evaluation, never by the fusion.
    truth: str | None = None


class Sweep(BaseModel):
    """What the sensor reports once per sweep: where it is, and what it saw."""

    time: datetime
    sensor_id: str
    lat: float
    lon: float
    footprint_nm: float
    detections: list[Detection]


def position_along(path: list[Corner], distance_nm: float, loop: bool) -> Corner:
    """Point at `distance_nm` along a polyline (closed if `loop`), linear
    interpolation inside each leg (legs are a few nm, so flat is fine)."""
    pts = [*path, path[0]] if loop else list(path)
    legs = [haversine_nm(*a, *b) for a, b in zip(pts, pts[1:], strict=False)]
    total = sum(legs)
    if total == 0:
        return pts[0]
    d = distance_nm % total if loop else min(distance_nm, total)
    for (a, b), leg in zip(zip(pts, pts[1:], strict=False), legs, strict=False):
        if d <= leg:
            f = d / leg if leg else 0.0
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        d -= leg
    return pts[-1]


def _offset(lat: float, lon: float, north_m: float, east_m: float) -> Corner:
    return (
        lat + north_m / 1852 / 60,
        lon + east_m / 1852 / (60 * math.cos(math.radians(lat))),
    )


class DroneSimulator:
    def __init__(self, cfg: SensorsConfig, start: datetime) -> None:
        self.cfg = cfg
        self.start = start
        self.rng = random.Random(cfg.drone.seed)

    def _hours(self, t: datetime) -> float:
        return (t - self.start).total_seconds() / 3600

    def drone_position(self, t: datetime) -> Corner:
        d = self.cfg.drone
        return position_along(d.patrol, d.speed_kn * self._hours(t), loop=True)

    def dark_positions(self, t: datetime) -> dict[str, Corner]:
        return {
            dt.name: position_along(dt.path, dt.speed_kn * self._hours(t), dt.loop)
            for dt in self.cfg.dark_targets
        }

    def sweep(self, t: datetime, ais_tracks: list[Track]) -> Sweep:
        d = self.cfg.drone
        lat0, lon0 = self.drone_position(t)
        detections: list[Detection] = []

        def detect(lat: float, lon: float, truth: str) -> None:
            if self.rng.random() > d.pd:
                return  # missed
            n, e = self.rng.gauss(0, d.position_sigma_m), self.rng.gauss(0, d.position_sigma_m)
            dlat, dlon = _offset(lat, lon, n, e)
            detections.append(
                Detection(
                    time=t,
                    lat=dlat,
                    lon=dlon,
                    sigma_m=d.position_sigma_m,
                    sensor_id=d.id,
                    truth=truth,
                )
            )

        # Real ships: their latest AIS position is the best "truth" we have.
        for tr in ais_tracks:
            if (
                not tr.stale
                and haversine_nm(lat0, lon0, tr.latitude, tr.longitude) <= d.footprint_nm
            ):
                detect(tr.latitude, tr.longitude, f"ais:{tr.mmsi}")
        for name, (lat, lon) in self.dark_positions(t).items():
            if haversine_nm(lat0, lon0, lat, lon) <= d.footprint_nm:
                detect(lat, lon, f"dark:{name}")
        # Clutter: Poisson number of points, uniform over the footprint disc.
        for _ in range(self._poisson(d.false_alarms_per_sweep)):
            r = d.footprint_nm * 1852 * math.sqrt(self.rng.random())
            a = self.rng.random() * 2 * math.pi
            clat, clon = _offset(lat0, lon0, r * math.cos(a), r * math.sin(a))
            detections.append(
                Detection(
                    time=t,
                    lat=clat,
                    lon=clon,
                    sigma_m=d.position_sigma_m,
                    sensor_id=d.id,
                    truth="clutter",
                )
            )
        return Sweep(
            time=t,
            sensor_id=d.id,
            lat=lat0,
            lon=lon0,
            footprint_nm=d.footprint_nm,
            detections=detections,
        )

    def _poisson(self, mean: float) -> int:
        # Knuth's method; mean is small (< 5).
        limit, k, p = math.exp(-mean), 0, 1.0
        while True:
            p *= self.rng.random()
            if p <= limit:
                return k
            k += 1
