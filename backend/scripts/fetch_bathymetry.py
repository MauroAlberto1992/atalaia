"""Cut the EMODnet Bathymetry DTM 2024 to a configured area (phase 17a).

Run from backend/:  python scripts/fetch_bathymetry.py [--area algarve]

Downloads the ESRI ASCII tile(s) covering each box of the area from
downloads.emodnet-bathymetry.eu, keeps only the cells inside the box (plus a
small margin), and writes config/bathymetry/<area>.bin.gz (see
minicop/bathymetry.py for the format).

Source: EMODnet Digital Bathymetry (DTM 2024), ~115 m grid, CC BY 4.0.
"This data product was created by EMODnet (https://emodnet.ec.europa.eu/en/),
and is owned by the EU and licensed under the Creative Commons Attribution 4.0
International (CC BY 4.0) license." NOT FOR NAVIGATION.

Facts about the file, from the real F3 tile (not from documentation):
- header: ncols, nrows, xllcorner, yllcorner, cellsize (1/960 deg), nodata_value 99;
- values are ELEVATION in metres: negative at sea, and land is nodata (99);
- the first row is the northernmost; values wrap 10 per text line, so rows
  must be read as a stream of numbers, not line by line.
"""

import argparse
import io
import itertools
import urllib.request
import zipfile
from collections.abc import Iterator
from pathlib import Path

from minicop.bathymetry import Grid, write_grids
from minicop.config import BACKEND_DIR, load_area

BASE_URL = "https://downloads.emodnet-bathymetry.eu/v12"
MARGIN_DEG = 0.05  # a little beyond the box, so ships at the edge still get a depth
# Tiles of the DTM 2024 (from the EMODnet catalogue): name -> lon_min, lon_max, lat_min, lat_max.
TILES = {"F3": (-16.252, -6.3729, 33.7479, 43.127)}


def tile_for(lat_min: float, lon_min: float, lat_max: float, lon_max: float) -> str:
    for name, (w, e, s, n) in TILES.items():
        if w <= lon_min and lon_max <= e and s <= lat_min and lat_max <= n:
            return name
    raise SystemExit(
        f"No known tile covers {lat_min},{lon_min} - {lat_max},{lon_max}; add it to TILES"
    )


def numbers(text: io.TextIOBase) -> Iterator[str]:
    for line in text:
        yield from line.split()


def cut(asc: io.TextIOBase, lat_min: float, lon_min: float, lat_max: float, lon_max: float) -> Grid:
    header = {}
    for _ in range(6):
        key, value = asc.readline().split()
        header[key.lower()] = float(value)
    ncols, nrows = int(header["ncols"]), int(header["nrows"])
    x0, y0, cs = header["xllcorner"], header["yllcorner"], header["cellsize"]
    nodata = header["nodata_value"]
    y_top = y0 + nrows * cs
    r0, r1 = max(0, int((y_top - lat_max) / cs)), min(nrows, int((y_top - lat_min) / cs) + 1)
    c0, c1 = max(0, int((lon_min - x0) / cs)), min(ncols, int((lon_max - x0) / cs) + 1)
    stream = numbers(asc)
    for _ in itertools.islice(stream, r0 * ncols):
        pass  # rows north of the box
    rows: list[list[int | None]] = []
    for _ in range(r1 - r0):
        row = list(itertools.islice(stream, ncols))[c0:c1]
        rows.append([None if float(v) == nodata else round(-float(v)) for v in row])
    return Grid(
        lat_top=y_top - r0 * cs,
        lon_left=x0 + c0 * cs,
        cell_deg=cs,
        depths=rows,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--area", default="algarve")
    args = parser.parse_args()
    area = load_area(args.area)
    grids = []
    for (lat_min, lon_min), (lat_max, lon_max) in area.boxes:
        box = (
            lat_min - MARGIN_DEG,
            lon_min - MARGIN_DEG,
            lat_max + MARGIN_DEG,
            lon_max + MARGIN_DEG,
        )
        tile = tile_for(*box)
        url = f"{BASE_URL}/{tile}_2024.asc.zip"
        print(f"Downloading {url} ...")
        with urllib.request.urlopen(url, timeout=600) as r:  # ~200 MB
            data = r.read()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = next(n for n in z.namelist() if n.endswith(".asc"))
            with z.open(name) as f:
                grid = cut(io.TextIOWrapper(f, encoding="ascii"), *box)
        sea = sum(d is not None for row in grid.depths for d in row)
        print(f"  {len(grid.depths)} x {len(grid.depths[0])} cells, {sea} at sea")
        grids.append(grid)
    out: Path = BACKEND_DIR / "config" / "bathymetry" / f"{args.area}.bin.gz"
    write_grids(out, grids)
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
