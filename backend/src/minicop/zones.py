"""Zones of interest, loaded from config/zones.toml."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, computed_field

from minicop.config import BACKEND_DIR, Corner
from minicop.geo import point_in_polygon

DEFAULT_ZONES_FILE = BACKEND_DIR / "config" / "zones.toml"


class Zone(BaseModel):
    name: str
    kind: str
    alert_on_entry: bool = False
    max_speed_kn: float | None = None
    polygon: list[Corner] = Field(min_length=3)  # [lat, lon] vertices

    @computed_field  # included in the JSON for the frontend
    @property
    def bbox(self) -> tuple[Corner, Corner]:
        lats = [p[0] for p in self.polygon]
        lons = [p[1] for p in self.polygon]
        return (min(lats), min(lons)), (max(lats), max(lons))

    def contains(self, lat: float, lon: float) -> bool:
        # Cheap rectangle check first; most ships are far from most zones.
        (lat_min, lon_min), (lat_max, lon_max) = self.bbox
        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            return False
        return point_in_polygon(lat, lon, self.polygon)


def load_zones(path: Path = DEFAULT_ZONES_FILE) -> list[Zone]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    zones = [Zone(**z) for z in data.get("zones", [])]
    names = [z.name for z in zones]
    if len(names) != len(set(names)):
        raise ValueError("Zone names must be unique (they identify zones in alerts)")
    return zones
