"""Phase 17a: depth lookups on the committed EMODnet cut of the Algarve.

Expected values were read from the original EMODnet DTM 2024 tile F3
(F3_2024.asc, elevation in metres, rounded) at the same coordinates, so these
tests check the cut and the lookup against the source, not against memory.
"""

from pathlib import Path

from minicop.bathymetry import Bathymetry, Grid, load_bathymetry, write_grids

B = load_bathymetry("algarve")


def test_the_algarve_cut_is_committed():
    assert B is not None


def test_depths_match_the_source_tile():
    assert B is not None
    assert B.depth_m(37.09, -8.53) == 25  # ~1 nm off Portimão (source: -24.75)
    assert B.depth_m(36.95, -8.53) == 65  # ~10 nm off Portimão (source: -64.84)
    assert B.depth_m(37.00, -8.94) == 13  # just off Cape São Vicente/Sagres (source: -12.93)


def test_land_is_land_and_outside_is_unknown():
    assert B is not None
    assert B.depth_m(37.138, -8.537) is None and B.is_land(37.138, -8.537)  # Portimão town
    assert B.is_land(37.017, -7.97)  # Faro airport
    assert not B.covers(32.7, -16.9)  # Madeira: not in the Algarve cut
    assert not B.is_land(32.7, -16.9)


def test_round_trip_keeps_values_and_land(tmp_path: Path):
    grid = Grid(
        lat_top=37.0, lon_left=-9.0, cell_deg=0.01, depths=[[10, 12, None], [3000, 2990, 5]]
    )
    path = tmp_path / "t.bin.gz"
    write_grids(path, [grid])
    b = Bathymetry(path)
    assert b.depth_m(36.995, -8.995) == 10
    assert b.depth_m(36.995, -8.975) is None and b.is_land(36.995, -8.975)
    assert b.depth_m(36.985, -8.995) == 3000  # big jump between rows/cells survives the deltas
    assert b.depth_m(36.985, -8.975) == 5
