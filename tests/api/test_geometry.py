from custom_components.noaa_spc.api.geometry import point_in_any, point_in_polygon

SQUARE = (((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)),)
HOLE = ((4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0), (4.0, 4.0))
L_SHAPE = (
    (
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 2.0),
        (2.0, 2.0),
        (2.0, 10.0),
        (0.0, 10.0),
        (0.0, 0.0),
    ),
)


def test_inside_and_outside_square() -> None:
    assert point_in_polygon(5.0, 5.0, SQUARE)
    assert not point_in_polygon(15.0, 5.0, SQUARE)
    assert not point_in_polygon(5.0, -1.0, SQUARE)


def test_hole_excludes_point() -> None:
    donut = (SQUARE[0], HOLE)
    assert not point_in_polygon(5.0, 5.0, donut)
    assert point_in_polygon(1.0, 1.0, donut)


def test_concave_polygon() -> None:
    assert point_in_polygon(1.0, 9.0, L_SHAPE)
    assert not point_in_polygon(6.0, 6.0, L_SHAPE)


def test_empty_polygon_is_never_inside() -> None:
    assert not point_in_polygon(0.0, 0.0, ())


def test_vertex_does_not_raise() -> None:
    point_in_polygon(0.0, 0.0, SQUARE)
    point_in_polygon(10.0, 10.0, SQUARE)


def test_point_in_any_multipolygon() -> None:
    far = (((20.0, 20.0), (30.0, 20.0), (30.0, 30.0), (20.0, 30.0), (20.0, 20.0)),)
    assert point_in_any(25.0, 25.0, (SQUARE, far))
    assert not point_in_any(15.0, 15.0, (SQUARE, far))
