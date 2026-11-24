"""Pydantic models for the aisstream.io message format.

aisstream uses PascalCase keys (e.g. "UserID", "TrueHeading"). We expose
snake_case attributes and map them with `alias`, so the rest of the code
never sees the wire names.
"""

from pydantic import BaseModel, ConfigDict, Field


class PositionReport(BaseModel):
    """AIS message types 1/2/3: a Class A ship reporting where it is."""

    model_config = ConfigDict(populate_by_name=True)

    mmsi: int = Field(alias="UserID")  # 9-digit ship identity
    latitude: float = Field(alias="Latitude")  # degrees; 91 = not available
    longitude: float = Field(alias="Longitude")  # degrees; 181 = not available
    sog: float = Field(alias="Sog")  # speed over ground, knots
    cog: float = Field(alias="Cog")  # course over ground, degrees
    true_heading: int = Field(alias="TrueHeading")  # bow direction; 511 = not available
    navigational_status: int = Field(alias="NavigationalStatus")  # 0 under way, 1 anchored, 5 moored...
    timestamp: int = Field(alias="Timestamp")  # UTC second of the minute (0-59)


class MetaData(BaseModel):
    """Fields aisstream adds to every message."""

    mmsi: int = Field(alias="MMSI")
    ship_name: str = Field(default="", alias="ShipName")
    # Kept as a string in phase 1; aisstream uses a Go-style format
    # ("2024-01-01 12:00:00.123 +0000 UTC") that we parse when we need it.
    time_utc: str = Field(alias="time_utc")


class AisEnvelope(BaseModel):
    """Top-level message: the type, metadata, and a dict keyed by the type name."""

    message_type: str = Field(alias="MessageType")
    metadata: MetaData = Field(alias="MetaData")
    message: dict = Field(alias="Message")  # e.g. {"PositionReport": {...}}
