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


class Track(BaseModel):
    """Latest known state of one ship. Phase 2: last position only."""

    mmsi: int
    ship_name: str
    latitude: float
    longitude: float
    sog: float
    cog: float
    true_heading: int
    navigational_status: int
    last_seen: datetime
