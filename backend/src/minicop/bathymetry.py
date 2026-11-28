"""Sea depth at a position, from a cut of the EMODnet DTM (phase 17a).

Source: EMODnet Digital Bathymetry (DTM 2024), ~115 m grid (1/16 arc minute),
CC BY 4.0, owned by the EU. NOT FOR NAVIGATION. The cut is made by
scripts/fetch_bathymetry.py.

File format (config/bathymetry/<area>.bin.gz, gzip): a JSON header line, then
for each grid its depths as int16 metres (positive down; LAND = -32768, i.e.
"no sea data"), row by row from north to south, each row stored as the first
value followed by differences (the seabed is smooth, so differences are small
and gzip packs them well).
"""

import gzip
import json
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
    depths: list[list[int | None]]  # metres, positive down; None = land


def _encode_row(row: list[int | None]) -> "array[int]":
    values = [LAND if d is None else max(-32767, min(32767, d)) for d in row]
    out = array("h", values[:1])
    out.extend((b - a + 32768) % 65536 - 32768 for a, b in zip(values, values[1:], strict=False))
    return out


def _decode_row(encoded: "array[int]") -> list[int]:
    values = [encoded[0]]
    for diff in encoded[1:]:
        values.append((values[-1] + diff + 32768) % 65536 - 32768)
    return values


def write_grids(path: Path, grids: list[Grid]) -> None:
    header = [
        {
            "lat_top": g.lat_top,
            "lon_left": g.lon_left,
            "cell_deg": g.cell_deg,
            "rows": len(g.depths),
            "cols": len(g.depths[0]),
        }
        for g in grids
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write((json.dumps({"source": ACKNOWLEDGEMENT, "grids": header}) + "\n").encode())
        for g in grids:
            for row in g.depths:
                f.write(_encode_row(row).tobytes())


class Bathymetry:
    """Loaded once at startup; depth_m() is a constant-time lookup."""

    def __init__(self, path: Path) -> None:
        with gzip.open(path, "rb") as f:
            meta = json.loads(f.readline())
            self._grids: list[tuple[dict[str, float], list[array[int]]]] = []
            for h in meta["grids"]:
                rows = []
                for _ in range(int(h["rows"])):
                    raw = array("h")
                    raw.frombytes(f.read(2 * int(h["cols"])))
                    rows.append(array("h", _decode_row(raw)))
                self._grids.append((h, rows))

    def _cell(self, lat: float, lon: float) -> int | None:
        for h, rows in self._grids:
            r = int((h["lat_top"] - lat) / h["cell_deg"])
            c = int((lon - h["lon_left"]) / h["cell_deg"])
            if 0 <= r < len(rows) and 0 <= c < int(h["cols"]):
                return int(rows[r][c])
        return None

    def covers(self, lat: float, lon: float) -> bool:
        return self._cell(lat, lon) is not None

    def depth_m(self, lat: float, lon: float) -> float | None:
        """Sea depth in metres (positive), or None on land or outside the grid."""
        v = self._cell(lat, lon)
        return None if v is None or v == LAND else float(v)

    def is_land(self, lat: float, lon: float) -> bool:
        return self._cell(lat, lon) == LAND


def load_bathymetry(area: str, directory: Path = DEFAULT_DIR) -> Bathymetry | None:
    path = directory / f"{area}.bin.gz"
    return Bathymetry(path) if path.exists() else None
