"""Cut the EMODnet Bathymetry DTM 2024 to a configured area (phase 17a).

Run from backend/:  python scripts/fetch_bathymetry.py [--area algarve]

Downloads the ESRI ASCII tile(s) covering each box of the area from
downloads.emodnet-bathymetry.eu, keeps only the cells inside the box (plus a
small margin), and writes config/bathymetry/<area>.bin.xz (see
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
from array import array
from collections.abc import Iterator
from pathlib import Path

from minicop.bathymetry import LAND, Grid, write_grids
from minicop.config import BACKEND_DIR, load_area

BASE_URL = "https://downloads.emodnet-bathymetry.eu/v12"
MARGIN_DEG = 0.05  # a little beyond the box, so ships at the edge still get a depth
# Tiles of the DTM 2024 (from the EMODnet catalogue): name -> lon_min, lon_max, lat_min, lat_max.
# Only the tiles the configured areas need (mainland: F3; Madeira: G2+G3; Azores: F1+F2).
TILES = {
    "F1": (-36.0, -26.1229, 33.7479, 43.127),
    "F2": (-26.127, -16.2479, 33.7479, 43.127),
    "F3": (-16.252, -6.3729, 33.7479, 43.127),
    "G2": (-26.127, -16.2479, 24.3729, 33.752),
    "G3": (-16.252, -6.3729, 24.3729, 33.752),
}

Box = tuple[float, float, float, float]  # lat_min, lon_min, lat_max, lon_max


def pieces(box: Box) -> list[tuple[str, Box]]:
    """The tiles a box needs, each with the part of the box inside it (a box
    can straddle two tiles: Madeira and the Azores do)."""
    lat_min, lon_min, lat_max, lon_max = box
    out = []
    for name, (w, e, s, n) in TILES.items():
        part = (max(lat_min, s), max(lon_min, w), min(lat_max, n), min(lon_max, e))
        if part[0] < part[2] and part[1] < part[3]:
            out.append((name, part))
    covered = sum((p[2] - p[0]) * (p[3] - p[1]) for _, p in out)
    if covered < 0.999 * (lat_max - lat_min) * (lon_max - lon_min):
        raise SystemExit(f"Box {box} is not fully covered by known tiles; add them to TILES")
    return out


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
    # Built straight into an int16 array (2 bytes per cell): the whole
    # mainland coast is ~18 M cells, too many for Python lists of ints.
    depths: array[int] = array("h")
    for _ in range(r1 - r0):
        row = list(itertools.islice(stream, ncols))[c0:c1]
        depths.extend(LAND if float(v) == nodata else round(-float(v)) for v in row)
    return Grid(
        lat_top=y_top - r0 * cs,
        lon_left=x0 + c0 * cs,
        cell_deg=cs,
        rows=r1 - r0,
        cols=c1 - c0,
        depths=depths,
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
        for tile, part in pieces(box):
            url = f"{BASE_URL}/{tile}_2024.asc.zip"
            print(f"Downloading {url} (about 200 MB) ...")
            with urllib.request.urlopen(url, timeout=900) as r:
                data = r.read()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                name = next(n for n in z.namelist() if n.endswith(".asc"))
                with z.open(name) as f:
                    grid = cut(io.TextIOWrapper(f, encoding="ascii"), *part)
            sea = sum(1 for d in grid.depths if d != LAND)
            print(f"  {tile}: {grid.rows} x {grid.cols} cells, {sea} at sea")
            grids.append(grid)
    out: Path = BACKEND_DIR / "config" / "bathymetry" / f"{args.area}.bin.xz"
    write_grids(out, grids)
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
