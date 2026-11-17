import pytest
from pydantic import ValidationError

from geopulse.schemas import Fence, PolygonQuery


@pytest.mark.parametrize("model", [Fence, PolygonQuery])
@pytest.mark.parametrize("geometry_type", ["Polygon", "MultiPolygon"])
@pytest.mark.parametrize(
    "position",
    [
        [10**400, 0],
        [-(10**400), 0],
        [0, 10**400],
        [0, -(10**400)],
        [float("nan"), 0],
        [0, float("inf")],
    ],
    ids=["huge-longitude", "negative-huge-longitude", "huge-latitude", "negative-huge-latitude", "nan", "infinity"],
)
def test_out_of_bounds_coordinates_are_validation_errors(model, geometry_type, position):
    rings = [[position, [1, 0], [1, 1], position]]
    geometry = {"type": geometry_type, "coordinates": rings if geometry_type == "Polygon" else [rings]}
    with pytest.raises(ValidationError):
        model(geometry=geometry, **({"name": "Invalid fence"} if model is Fence else {}))


@pytest.mark.parametrize("model", [Fence, PolygonQuery])
@pytest.mark.parametrize("geometry_type", ["Polygon", "MultiPolygon"])
def test_integer_boundary_coordinates_remain_valid(model, geometry_type):
    rings = [[[-180, -90], [180, -90], [180, 90], [-180, -90]]]
    geometry = {"type": geometry_type, "coordinates": rings if geometry_type == "Polygon" else [rings]}
    result = model(geometry=geometry, **({"name": "Boundary fence"} if model is Fence else {}))
    assert result.geometry == geometry
