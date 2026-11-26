from minicop.geo import point_in_polygon

SQUARE = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]  # (lat, lon)
# "U" shape: concave, with a notch from lat 5..10, lon 4..6.
U = [(0, 0), (10, 0), (10, 4), (5, 4), (5, 6), (10, 6), (10, 10), (0, 10)]


def test_inside_and_outside_square():
    assert point_in_polygon(5, 5, SQUARE)
    assert not point_in_polygon(15, 5, SQUARE)
    assert not point_in_polygon(5, -1, SQUARE)


def test_concave_notch_is_outside():
    assert point_in_polygon(2, 5, U)  # bottom of the U
    assert point_in_polygon(8, 2, U)  # left arm
    assert not point_in_polygon(8, 5, U)  # inside the notch


def test_vertex_order_does_not_matter():
    assert point_in_polygon(5, 5, list(reversed(SQUARE)))


def test_distance_to_polygon_edge():
    from minicop.geo import distance_to_polygon_nm

    # 1 minute of latitude north of a box's top edge = 1 nm.
    box = [(37.0, -8.1), (37.0, -8.0), (37.1, -8.0), (37.1, -8.1)]
    assert abs(distance_to_polygon_nm(37.1 + 1 / 60, -8.05, box) - 1.0) < 0.01
