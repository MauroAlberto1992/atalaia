"""Environmental context checks (phase 17a): positions that cannot be right.

A ship reported where the sea is shallower than its declared draught, or on
land well away from the coast, is aground or its position is wrong (GPS fault
or spoofing). Ports and the coastal band are excluded: in a port it is normal
to be close to land, and there the ~115 m grid cannot tell.

Runs in the state task, like the other monitors.
"""

import tomllib
from pathlib import Path

from pydantic import BaseModel

from minicop.alerts import Alert, AlertEngine, AlertKind
from minicop.bathymetry import Bathymetry
from minicop.config import BACKEND_DIR
from minicop.events import Track
from minicop.ports import PORT_MARGIN_NM
from minicop.zones import Zone

DEFAULT_CONTEXT_FILE = BACKEND_DIR / "config" / "context.toml"


class ContextConfig(BaseModel):
    draught_margin_m: float
    coast_margin_m: float


def load_context_config(path: Path = DEFAULT_CONTEXT_FILE) -> ContextConfig:
    with path.open("rb") as f:
        return ContextConfig(**tomllib.load(f))


UNKNOWN = "unknown"  # can't tell here (outside the grid, port, coastal band, no draught)


def judge(
    track: Track, bathymetry: Bathymetry, cfg: ContextConfig, ports: list[Zone]
) -> str | None:
    """A reason the position can't be right; None if it is plausible; or
    UNKNOWN when this place (or a missing draught) doesn't allow a verdict."""
    lat, lon = track.latitude, track.longitude
    if not bathymetry.covers(lat, lon):
        return UNKNOWN
    if any(p.near(lat, lon, PORT_MARGIN_NM) for p in ports):
        return UNKNOWN
    land_near, sea_near = bathymetry.surroundings(lat, lon, cfg.coast_margin_m)
    if land_near and sea_near:
        return UNKNOWN  # coastal band: the grid is too coarse here
    if not sea_near:
        return f"position on land (no sea within {cfg.coast_margin_m:.0f} m)"
    depth = bathymetry.depth_m(lat, lon)
    draught = track.draught_m
    if depth is None or draught is None:
        return UNKNOWN
    if depth < draught + cfg.draught_margin_m:
        return (
            f"sea depth ~{depth:.0f} m, declared draught {draught:.1f} m "
            f"(margin {cfg.draught_margin_m:g} m)"
        )
    return None


def impossible_reason(
    track: Track, bathymetry: Bathymetry, cfg: ContextConfig, ports: list[Zone]
) -> str | None:
    """Why this position can't be right, or None (possible, or can't tell)."""
    verdict = judge(track, bathymetry, cfg, ports)
    return None if verdict == UNKNOWN else verdict


class ContextMonitor:
    def __init__(
        self,
        cfg: ContextConfig,
        bathymetry: Bathymetry | None,
        zones: list[Zone],
        alerts: AlertEngine,
    ) -> None:
        self.cfg = cfg
        self.bathymetry = bathymetry
        self._ports = [z for z in zones if z.kind == "port"]
        self._alerts = alerts
        self._flagged: set[int] = set()  # in an "impossible" episode: alert once

    def on_track(self, track: Track) -> list[Alert]:
        if self.bathymetry is None:
            return []
        reason = judge(track, self.bathymetry, self.cfg, self._ports)
        if reason is None:
            self._flagged.discard(track.mmsi)  # plausible again: re-arm
            return []
        if reason == UNKNOWN:
            return []  # can't tell here: keep the episode as it is (review fix)
        if track.mmsi in self._flagged:
            return []
        self._flagged.add(track.mmsi)
        name = track.ship_name or str(track.mmsi)
        return [
            self._alerts.record(
                AlertKind.IMPOSSIBLE_POSITION,
                track,
                track.last_seen,
                f"{name}: impossible position, {reason}. Aground, or a wrong/spoofed position.",
            )
        ]

    def on_removed(self, mmsi: int) -> None:
        self._flagged.discard(mmsi)
