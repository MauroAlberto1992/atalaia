"""Port areas from OpenStreetMap, used to suppress alerts where stopping,
mooring side by side or switching AIS off is normal.

The data is fetched once by scripts/fetch_ports.py and committed as
config/ports.json; the service never calls OpenStreetMap at runtime.
Data © OpenStreetMap contributors, ODbL (https://www.openstreetmap.org/copyright).
"""

import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from minicop.config import BACKEND_DIR, Corner
from minicop.geo import haversine_nm, point_in_polygon
from minicop.zones import Zone

DEFAULT_PORTS_FILE = BACKEND_DIR / "config" / "ports.json"

# Points without a mapped outline become a circle of this radius.
POINT_RADIUS_NM = 0.5
# Points closer than this to another port are the same place mapped twice.
MERGE_DISTANCE_NM = 0.5


class Port(BaseModel):
    name: str
    kind: str  # "harbour" | "fishing" | "marina"
    osm: str  # e.g. "way/123456", for traceability back to the source
    polygon: list[Corner]  # [lat, lon] vertices


def _kind(tags: dict[str, str]) -> str:
    if tags.get("leisure") == "marina":
        return "marina"
    if "fishing" in tags.get("seamark:harbour:category", ""):
        return "fishing"
    return "harbour"


def circle(lat: float, lon: float, radius_nm: float, sides: int = 16) -> list[Corner]:
    """Polygon approximating a circle (flat lon/lat, fine at this size)."""
    dlat = radius_nm / 60
    dlon = radius_nm / (60 * math.cos(math.radians(lat)))
    return [
        (
            lat + dlat * math.sin(2 * math.pi * i / sides),
            lon + dlon * math.cos(2 * math.pi * i / sides),
        )
        for i in range(sides)
    ]


def _outline(element: dict[str, Any]) -> list[Corner] | None:
    """The mapped outline of a way, or the largest closed outer ring of a
    relation. None when OSM only has a point (or no closed ring)."""
    rings: list[list[dict[str, float]]] = []
    if element["type"] == "way":
        rings = [element.get("geometry", [])]
    elif element["type"] == "relation":
        rings = [
            m.get("geometry", [])
            for m in element.get("members", [])
            if m.get("role") == "outer" and m.get("type") == "way"
        ]
    closed = [r for r in rings if len(r) >= 4 and r[0] == r[-1]]
    if not closed:
        return None
    ring = max(closed, key=len)
    return [(p["lat"], p["lon"]) for p in ring[:-1]]  # drop the repeated last vertex


def _anchor(element: dict[str, Any]) -> tuple[float, float] | None:
    """A representative point: the node itself, Overpass' computed centre, or
    the middle of the bounds. (With `out geom`, Overpass returns bounds but no
    centre for relations; the first parser dropped them silently.)"""
    if element["type"] == "node":
        return element["lat"], element["lon"]
    centre = element.get("center")
    if centre:
        return centre["lat"], centre["lon"]
    bounds = element.get("bounds")
    if bounds:
        return (
            (bounds["minlat"] + bounds["maxlat"]) / 2,
            (bounds["minlon"] + bounds["maxlon"]) / 2,
        )
    return None


def ports_from_overpass(data: dict[str, Any]) -> list[Port]:
    """Turn an Overpass JSON response (`out center tags geom;`) into ports.

    De-duplication: mapped outlines are kept first; a point is dropped if it
    lies inside a kept outline or within MERGE_DISTANCE_NM of a kept point.
    """
    with_outline: list[Port] = []
    points: list[tuple[Port, float, float]] = []
    for el in data.get("elements", []):
        tags: dict[str, str] = el.get("tags", {})
        name = tags.get("name") or tags.get("seamark:name") or "Unnamed harbour"
        ref = f"{el['type']}/{el['id']}"
        outline = _outline(el)
        if outline is not None and len(outline) >= 3:
            with_outline.append(Port(name=name, kind=_kind(tags), osm=ref, polygon=outline))
            continue
        anchor = _anchor(el)
        if anchor is not None:
            lat, lon = anchor
            port = Port(
                name=name, kind=_kind(tags), osm=ref, polygon=circle(lat, lon, POINT_RADIUS_NM)
            )
            points.append((port, lat, lon))

    kept = list(with_outline)
    kept_points: list[tuple[float, float]] = []
    for port, lat, lon in points:
        if any(point_in_polygon(lat, lon, p.polygon) for p in with_outline):
            continue
        if any(haversine_nm(lat, lon, a, b) < MERGE_DISTANCE_NM for a, b in kept_points):
            continue
        kept.append(port)
        kept_points.append((lat, lon))
    return sorted(kept, key=lambda p: (p.name, p.osm))


def load_ports(path: Path = DEFAULT_PORTS_FILE) -> list[Zone]:
    """Port zones for the alert engines (kind="port": they raise no alerts)."""
    data = json.loads(path.read_text())
    return [
        Zone(name=f"{p['name']} ({p['kind']})", kind="port", polygon=p["polygon"])
        for p in data["ports"]
    ]
