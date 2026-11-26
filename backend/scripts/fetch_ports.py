"""Fetch port areas for Portugal from OpenStreetMap and write config/ports.json.

Run from backend/ (one-off; the output is committed, the service never calls
OpenStreetMap at runtime):

    python scripts/fetch_ports.py                                  # query Overpass
    python scripts/fetch_ports.py --from-file data/osm/ports-raw.json  # use an export

--from-file: the development environment couldn't reach the Overpass API, so
the raw data was exported from https://overpass-turbo.eu ("raw OSM data")
with the query this script prints (--print-query) and committed.

Data © OpenStreetMap contributors, ODbL (https://www.openstreetmap.org/copyright).
"""

import argparse
import json
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime

from minicop.config import load_area
from minicop.ports import DEFAULT_PORTS_FILE, ports_from_overpass

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Harbour areas, nautical harbour marks (incl. fishing harbours) and marinas.
# `out center tags geom`: outlines for ways/relations, a centre for every element.
# The first, narrower query (landuse/seamark harbour + marina) missed major
# fishing and commercial ports such as Peniche and Leixões.
FILTERS = [
    'nwr["landuse"="harbour"]',
    'nwr["seamark:type"~"^(harbour|harbour_basin)$"]',
    'nwr["leisure"="marina"]',
    'nwr["industrial"="port"]',
    'nwr["harbour"]',
]


def build_query(boxes: list[tuple[tuple[float, float], tuple[float, float]]]) -> str:
    parts = []
    for (lat_min, lon_min), (lat_max, lon_max) in boxes:
        bbox = f"({lat_min},{lon_min},{lat_max},{lon_max})"  # Overpass: south,west,north,east
        parts += [f"{f}{bbox};" for f in FILTERS]
    return f"[out:json][timeout:180];({''.join(parts)});out center tags geom;"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--area", default="portugal")
    parser.add_argument("--raw", help="also save the raw Overpass response here")
    parser.add_argument("--from-file", help="read a raw Overpass export instead of querying")
    parser.add_argument("--print-query", action="store_true", help="print the query and exit")
    args = parser.parse_args()

    area = load_area(args.area)
    query = build_query(area.boxes)
    if args.print_query:
        print(query)
        return
    if args.from_file:
        with open(args.from_file) as f:
            data = json.load(f)
    else:
        body = urllib.parse.urlencode({"data": query}).encode()
        request = urllib.request.Request(
            OVERPASS_URL, data=body, headers={"User-Agent": "minicop-port-fetch/1.0"}
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.load(response)
        if args.raw:
            with open(args.raw, "w") as f:
                json.dump(data, f)

    ports = ports_from_overpass(data)
    out = {
        "source": "OpenStreetMap via Overpass API",
        "licence": "ODbL 1.0, (c) OpenStreetMap contributors, https://www.openstreetmap.org/copyright",
        # When the OSM data itself was current (from the export), and when
        # this file was generated.
        "osm_data_as_of": data.get("osm3s", {}).get("timestamp_osm_base", "unknown"),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "from_file": args.from_file,
        "area": args.area,
        "query": query,
        "ports": [p.model_dump() for p in ports],
    }
    DEFAULT_PORTS_FILE.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    kinds = Counter(p.kind for p in ports)
    print(f"{len(data.get('elements', []))} OSM elements -> {len(ports)} ports {dict(kinds)}")
    print(f"written to {DEFAULT_PORTS_FILE}")


if __name__ == "__main__":
    main()
