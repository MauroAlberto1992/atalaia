"""Internal domain types. Unlike models.py (aisstream's wire format), these are
ours: snake_case, validated, with real datetimes."""

from datetime import datetime

from pydantic import BaseModel


class PositionEvent(BaseModel):
    """One position report from one ship, as produced by ingestion."""

    mmsi: int
    latitude: float
    longitude: float
    sog: float
    cog: float
    true_heading: int
    navigational_status: int
    ship_name: str
    received_at: datetime  # aisstream's time_utc, timezone-aware (UTC)
    ais_class: str = "A"  # "A" (ships) or "B" (small craft)


class Track(BaseModel):
    """Latest known state of one ship, plus route stats (phase 4).
    The route points themselves are served separately by /tracks/{mmsi}/history."""

    mmsi: int
    ship_name: str
    latitude: float
    longitude: float
    sog: float
    cog: float
    true_heading: int
    navigational_status: int
    last_seen: datetime
    ais_class: str = "A"
    # Last time a (simulated) sensor detection was associated with this AIS
    # track (phase 15): "AIS + sensor" while recent.
    sensor_seen: datetime | None = None
    stale: bool = False  # no report for STALE_AFTER (phase 5)
    distance_nm: float = 0.0  # over the stored history
    avg_speed_kn: float = 0.0


class Tick(BaseModel):
    """Clock event, put on the same queue as positions so that the state task
    (the single writer) is also the one that expires tracks."""

    now: datetime


class SensorTick(BaseModel):
    """Clock event for the (simulated) sensor: run one sweep at `now`."""

    now: datetime
