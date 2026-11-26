"""Zones of interest, loaded from config/zones.toml."""

import math
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr, computed_field

from minicop.config import BACKEND_DIR, Corner
from minicop.geo import distance_to_polygon_nm, point_in_polygon

DEFAULT_ZONES_FILE = BACKEND_DIR / "config" / "zones.toml"


class Zone(BaseModel):
    name: str
    kind: str
    alert_on_entry: bool = False
    max_speed_kn: float | None = None
    polygon: list[Corner] = Field(min_length=3)  # [lat, lon] vertices

    _bbox: tuple[Corner, Corner] = PrivateAttr()

    def model_post_init(self, context: Any, /) -> None:
        # Computed once here, not on every contains() call (which runs for
        # every zone on every position report).
        lats = [p[0] for p in self.polygon]
        lons = [p[1] for p in self.polygon]
        self._bbox = (min(lats), min(lons)), (max(lats), max(lons))

    # mypy doesn't understand decorators stacked on @property; this is the
    # pattern Pydantic documents, so the ignore is expected.
    @computed_field  # type: ignore[prop-decorator]  # included in the JSON
    @property
    def bbox(self) -> tuple[Corner, Corner]:
        return self._bbox

    def near(self, lat: float, lon: float, margin_nm: float) -> bool:
        """Inside the polygon, or within margin_nm of its edge."""
        (lat_min, lon_min), (lat_max, lon_max) = self.bbox
        dlat = margin_nm / 60
        dlon = margin_nm / (60 * math.cos(math.radians(lat)))
        if not (
            lat_min - dlat <= lat <= lat_max + dlat and lon_min - dlon <= lon <= lon_max + dlon
        ):
            return False
        return point_in_polygon(lat, lon, self.polygon) or (
            distance_to_polygon_nm(lat, lon, self.polygon) <= margin_nm
        )

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
