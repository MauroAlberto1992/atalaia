"""Sea depth at a position, from a cut of the EMODnet DTM (phase 17a).

Source: EMODnet Digital Bathymetry (DTM 2024), ~115 m grid (1/16 arc minute),
CC BY 4.0, owned by the EU. NOT FOR NAVIGATION. The cut is made by
scripts/fetch_bathymetry.py.

File format (config/bathymetry/<area>.bin.xz, LZMA): a JSON header line, then
for each grid its depths as int16 metres (positive down; LAND = -32768, i.e.
"no sea data"), row by row from north to south, with the low bytes of all
values first and then the high bytes ("byte shuffle"). Neighbouring depths
share their high byte, so this packs well (Algarve: 0.44 MB for 1.5 M cells,
vs 0.72 MB plain gzip), and unpacking is a few slice copies, no Python loop
per cell: the whole coast (~40 M cells) loads in about a second.
"""

import json
import lzma
import math
import struct
import zlib
from array import array
from dataclasses import dataclass
from pathlib import Path

from minicop.config import BACKEND_DIR

LAND = -32768  # int16 marker: no sea data (land, in this DTM)
DEFAULT_DIR = BACKEND_DIR / "config" / "bathymetry"
ACKNOWLEDGEMENT = (
    "Bathymetry: EMODnet Digital Bathymetry (DTM 2024), created by EMODnet "
    "(https://emodnet.ec.europa.eu/en/), owned by the EU, licensed under CC BY 4.0. "
    "Not for navigation."
)


@dataclass
class Grid:
    lat_top: float  # north edge of the first row
    lon_left: float  # west edge of the first column
    cell_deg: float
    rows: int
    cols: int
    depths: "array[int]"  # rows * cols int16, metres positive down; LAND = no sea data

    @classmethod
    def from_rows(
        cls, lat_top: float, lon_left: float, cell_deg: float, rows: list[list[int | None]]
    ) -> "Grid":
        flat = array("h")
        for row in rows:
            flat.extend(LAND if d is None else max(-32767, min(32767, d)) for d in row)
        return cls(lat_top, lon_left, cell_deg, len(rows), len(rows[0]), flat)


def _shuffle(values: "array[int]") -> bytes:
    raw = values.tobytes()
    return raw[0::2] + raw[1::2]


def _unshuffle(data: bytes) -> "array[int]":
    n = len(data) // 2
    raw = bytearray(len(data))
    raw[0::2] = data[:n]
    raw[1::2] = data[n:]
    out = array("h")
    out.frombytes(bytes(raw))
    return out


def write_grids(path: Path, grids: list[Grid]) -> None:
    header = [
        {
            "lat_top": g.lat_top,
            "lon_left": g.lon_left,
            "cell_deg": g.cell_deg,
            "rows": g.rows,
            "cols": g.cols,
        }
        for g in grids
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with lzma.open(path, "wb", preset=9) as f:
        f.write((json.dumps({"source": ACKNOWLEDGEMENT, "grids": header}) + "\n").encode())
        for g in grids:
            f.write(_shuffle(g.depths))


class Bathymetry:
    """Loaded once at startup; depth_m() is a constant-time lookup."""

    def __init__(self, path: Path) -> None:
        with lzma.open(path, "rb") as f:
            meta = json.loads(f.readline())
            self._grids: list[Grid] = []
            for h in meta["grids"]:
                rows, cols = int(h["rows"]), int(h["cols"])
                depths = _unshuffle(f.read(2 * rows * cols))
                self._grids.append(
                    Grid(h["lat_top"], h["lon_left"], h["cell_deg"], rows, cols, depths)
                )

    def _cell(self, lat: float, lon: float) -> int | None:
        for g in self._grids:
            r = int((g.lat_top - lat) / g.cell_deg)
            c = int((lon - g.lon_left) / g.cell_deg)
            if 0 <= r < g.rows and 0 <= c < g.cols:
                return int(g.depths[r * g.cols + c])
        return None

    def surroundings(self, lat: float, lon: float, radius_m: float) -> tuple[bool, bool]:
        """(any land, any sea) among the cells within ~radius_m (a square of
        cells around the point). Used to skip places too close to the coast for
        a ~115 m grid to say anything."""
        for g in self._grids:
            r = int((g.lat_top - lat) / g.cell_deg)
            c = int((lon - g.lon_left) / g.cell_deg)
            if not (0 <= r < g.rows and 0 <= c < g.cols):
                continue
            n = max(1, round(radius_m / (g.cell_deg * 111_320)))  # cells (north-south size)
            land = sea = False
            c0, c1 = max(0, c - n), min(g.cols, c + n + 1)
            for rr in range(max(0, r - n), min(g.rows, r + n + 1)):
                for v in g.depths[rr * g.cols + c0 : rr * g.cols + c1]:
                    if v == LAND:
                        land = True
                    else:
                        sea = True
            return land, sea
        return False, False

    def grids(self) -> list[dict[str, float]]:
        """Bounds of each grid, for the map overlay."""
        return [
            {
                "south": g.lat_top - g.rows * g.cell_deg,
                "west": g.lon_left,
                "north": g.lat_top,
                "east": g.lon_left + g.cols * g.cell_deg,
            }
            for g in self._grids
        ]

    def shading_png(self, index: int, step: int = 2) -> bytes:
        """A PNG of one grid for the map: depth as shades of blue (log scale,
        light = shallow), land transparent. Every `step`-th cell, to keep it light."""
        g = self._grids[index]
        scale = math.log10(1 + 4000)
        palette: dict[int, bytes] = {}  # depth -> RGBA bytes (few distinct values: cache them)
        pixels = bytearray()
        row_range = range(0, g.rows, step)
        width = len(range(0, g.cols, step))
        for r in row_range:
            pixels.append(0)  # PNG filter type "none" for this row
            for v in g.depths[r * g.cols : (r + 1) * g.cols : step]:
                px = palette.get(v)
                if px is None:
                    if v == LAND:
                        px = b"\x00\x00\x00\x00"
                    else:
                        t = min(1.0, math.log10(1 + max(0, v)) / scale)
                        px = bytes(
                            (int(170 - 160 * t), int(220 - 180 * t), int(250 - 150 * t), 150)
                        )
                    palette[v] = px
                pixels += px
        return _png(width, len(row_range), bytes(pixels))

    def covers(self, lat: float, lon: float) -> bool:
        return self._cell(lat, lon) is not None

    def depth_m(self, lat: float, lon: float) -> float | None:
        """Sea depth in metres (positive), or None on land or outside the grid."""
        v = self._cell(lat, lon)
        return None if v is None or v == LAND else float(v)

    def is_land(self, lat: float, lon: float) -> bool:
        return self._cell(lat, lon) == LAND


def _png(width: int, height: int, rgba_rows: bytes) -> bytes:
    """Minimal RGBA PNG writer (standard library only)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rgba_rows, 6))
        + chunk(b"IEND", b"")
    )


def load_bathymetry(area: str, directory: Path = DEFAULT_DIR) -> Bathymetry | None:
    path = directory / f"{area}.bin.xz"
    return Bathymetry(path) if path.exists() else None
