import os

os.environ.setdefault("JWT_SECRET", "unit-test-only-secret-at-least-32-characters")
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from pydantic import ValidationError
from geopulse.schemas import Location, Fence, Optimization
from geopulse.security import access_token, decode_access, digest, passwords, verify_password
from geospatial import distance, optimize, state
from simulator.main import path_point


def point(**kwargs):
    return Location(event_id=uuid4(), recorded_at=datetime.now(timezone.utc), lng=34.46, lat=31.5, **kwargs)


@pytest.mark.parametrize(
    "field,value",
    [("lat", 91), ("lng", 181), ("speed", -1), ("bearing", 360), ("accuracy", float("nan")), ("battery_level", 101)],
)
def test_invalid_point(field, value):
    data = point().model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        Location(**data)


def test_timestamps():
    data = point().model_dump()
    for stamp in (datetime.now(), datetime.now(timezone.utc) + timedelta(hours=1)):
        data["recorded_at"] = stamp
        with pytest.raises(ValidationError):
            Location(**data)


def test_geo_units():
    assert 111000 < distance((0, 0), (0, 1)) < 112000
    assert distance((0, 0), (0, 0)) == 0


def test_optimizer():
    stops = [(0, 3), (0, 1), (0, 2), (1, 2)]
    result = optimize(stops, (0, 0), (0, 4))
    assert sorted(result["order"]) == list(range(4))
    assert result["distance_m"] <= result["initial_distance_m"] + 0.1
    assert optimize([], (0, 0))["order"] == []


def test_states():
    assert state(10, 5, 0) == "moving"
    assert state(0, 5, 100) == "idle"
    assert state(0, 5, 200) == "stopped"
    assert state(10, 150, 0) == "offline"


def test_auth():
    uid = uuid4()
    assert decode_access(access_token(uid)) == uid
    hashed = passwords.hash("long-test-password")
    assert verify_password("long-test-password", hashed)
    assert not verify_password("incorrect", hashed)
    assert digest("secret") != "secret"


def test_polygon_ring_validation():
    with pytest.raises(ValidationError):
        Fence(name="bad", geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [2, 0], [3, 2]]]})


def test_optimizer_bounds():
    with pytest.raises(ValidationError):
        Optimization(start=(200, 0), stops=[(0, 0)])


def test_simulator_path_moves():
    a = path_point(0)
    b = path_point(100)
    assert 98 < distance(a[:2], b[:2]) < 102
    assert a != b


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "Polygon", "coordinates": [None]},
        {"type": "Polygon", "coordinates": [[None]]},
        {"type": "Polygon", "coordinates": [[[1, 2, 3, 1]]]},
        {"type": "Polygon", "coordinates": [[[None, None, None, None]]]},
        {"type": "Polygon", "coordinates": [[[True, 0], [1, 0], [1, 1], [True, 0]]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, float("inf")], [0, 0]]]},
        {"type": "Point", "coordinates": [0, 0]},
        {"type": "MultiPolygon", "coordinates": []},
        {"type": "Polygon", "coordinates": [[[0, 0]] * 5001]},
    ],
)
def test_malformed_spatial_polygons_are_validation_errors(geometry):
    from geopulse.schemas import PolygonQuery

    for model, extra in [(PolygonQuery, {}), (Fence, {"name": "Invalid"})]:
        with pytest.raises(ValidationError):
            model(geometry=geometry, **extra)
