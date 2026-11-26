"""Port areas from OpenStreetMap: parsing a real Overpass export, and the
committed ports.json."""

import json
from pathlib import Path

from minicop.config import load_area
from minicop.geo import point_in_polygon
from minicop.ports import DEFAULT_PORTS_FILE, load_ports, ports_from_overpass

# Three genuine elements from the committed export: a way with an outline
# (Porto do Funchal), a node (Porto do Seixal), a relation with bounds only.
SAMPLE = json.loads((Path(__file__).parent / "fixtures" / "overpass_sample.json").read_text())


def test_way_outline_is_used_as_polygon():
    ports = {p.osm.split("/")[0]: p for p in ports_from_overpass(SAMPLE)}
    way = ports["way"]
    assert way.name == "Porto do Funchal"
    assert len(way.polygon) >= 3


def test_node_becomes_a_circle():
    node = next(p for p in ports_from_overpass(SAMPLE) if p.osm.startswith("node/"))
    assert len(node.polygon) == 16


def test_relation_with_bounds_only_is_kept():
    """Overpass gives relations bounds but no centre with `out geom`; the
    first parser silently dropped them."""
    assert any(p.osm.startswith("relation/") for p in ports_from_overpass(SAMPLE))


def test_point_inside_an_outline_is_merged():
    way = next(e for e in SAMPLE["elements"] if e["type"] == "way")
    lats = [g["lat"] for g in way["geometry"]]
    lons = [g["lon"] for g in way["geometry"]]
    inside = {  # a point at the outline's centre, as a duplicate harbour mark
        "type": "node",
        "id": 1,
        "lat": sum(lats) / len(lats),
        "lon": sum(lons) / len(lons),
        "tags": {"seamark:type": "harbour", "name": "Duplicate"},
    }
    data = {"elements": [way, inside]}
    assert [p.name for p in ports_from_overpass(data)] == ["Porto do Funchal"]


def test_committed_ports_file_is_sourced_and_valid():
    data = json.loads(DEFAULT_PORTS_FILE.read_text())
    assert "OpenStreetMap" in data["source"] and "ODbL" in data["licence"]
    boxes = load_area("portugal").boxes
    for port in data["ports"]:
        assert len(port["polygon"]) >= 3
        lat, lon = port["polygon"][0]
        assert any(
            a[0] - 0.1 <= lat <= b[0] + 0.1 and a[1] - 0.1 <= lon <= b[1] + 0.1 for a, b in boxes
        ), port["name"]


def test_major_fishing_and_commercial_ports_are_covered():
    """The first, narrower query missed Peniche and Leixões. Checked by name
    from the data itself, not by coordinates written from memory (those were
    off by 66-560 m and made coverage look worse than it was)."""
    names = {p["name"] for p in json.loads(DEFAULT_PORTS_FILE.read_text())["ports"]}
    for expected in [
        "Porto de Pesca de Peniche",
        "Porto de Pesca de Sesimbra",
        "Porto Comercial de Sines",
        "Marina do Funchal",
    ]:
        assert expected in names


def test_ports_load_as_alert_free_zones():
    zones = load_ports()
    assert len(zones) > 300
    assert {z.kind for z in zones} == {"port"}
    # The port's own polygon contains its centroid (a real Funchal harbour point).
    funchal = next(z for z in zones if z.name.startswith("Porto do Funchal"))
    lat = sum(p[0] for p in funchal.polygon) / len(funchal.polygon)
    lon = sum(p[1] for p in funchal.polygon) / len(funchal.polygon)
    assert point_in_polygon(lat, lon, funchal.polygon)
