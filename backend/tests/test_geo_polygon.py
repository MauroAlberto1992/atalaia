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
