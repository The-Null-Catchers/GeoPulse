import math
from datetime import datetime, timezone, timedelta
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Registration(Input):
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    organization: str = Field(min_length=1, max_length=100)


class Login(Input):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class Refresh(Input):
    refresh_token: str | None = Field(default=None, max_length=200)


class Named(Input):
    name: str = Field(min_length=1, max_length=100)


class DeviceCreate(Named):
    device_type: Literal["vehicle", "person", "asset", "iot"] = "vehicle"
    team_id: UUID | None = None
    driver_id: UUID | None = None
    vehicle_id: UUID | None = None


class DeviceUpdate(Input):
    active: bool


class Location(Input):
    event_id: UUID
    recorded_at: datetime
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    altitude: float | None = Field(default=None, ge=-1000, le=100000)
    speed: float = Field(default=0, ge=0, le=150)
    bearing: float = Field(default=0, ge=0, lt=360)
    accuracy: float = Field(default=10, ge=0, le=10000)
    battery_level: float | None = Field(default=None, ge=0, le=100)
    source: Literal["gps", "mobile", "simulator", "iot"] = "gps"

    @field_validator("recorded_at")
    @classmethod
    def timestamp(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must have timezone")
        if value > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("Timestamp is in the future")
        return value.astimezone(timezone.utc)


class Batch(Input):
    points: list[Location] = Field(min_length=1, max_length=500)


def validate_polygon(value):
    if not isinstance(value, dict) or value.get("type") not in ("Polygon", "MultiPolygon"):
        raise ValueError("Polygon or MultiPolygon required")
    polygons = [value.get("coordinates")] if value["type"] == "Polygon" else value.get("coordinates")
    if not isinstance(polygons, list) or not polygons or len(polygons) > 100:
        raise ValueError("Invalid or oversized polygon")
    count = 0
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValueError("Empty or invalid polygon")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Rings must be closed with at least 4 positions")
            count += len(ring)
            if count > 5000:
                raise ValueError("At most 5,000 positions allowed")
            for position in ring:
                if not isinstance(position, (list, tuple)) or len(position) != 2 or not all(
                    type(x) in (int, float) and math.isfinite(x) for x in position
                ):
                    raise ValueError("Invalid coordinate")
                if not -180 <= position[0] <= 180 or not -90 <= position[1] <= 90:
                    raise ValueError("Coordinate out of bounds")
    return value


class PolygonQuery(Input):
    geometry: dict

    @field_validator("geometry")
    @classmethod
    def polygon(cls, value):
        return validate_polygon(value)


class Fence(Named):
    geometry: dict | None = None
    center: tuple[float, float] | None = None
    radius_m: float | None = Field(default=None, ge=10, le=100000)
    dwell_seconds: int = Field(default=300, ge=1, le=86400)

    @field_validator("geometry")
    @classmethod
    def polygon(cls, value):
        return None if value is None else validate_polygon(value)


class RouteCreate(Named):
    waypoints: list[tuple[float, float]] = Field(min_length=2, max_length=50)

    @field_validator("waypoints")
    @classmethod
    def points(cls, value):
        if any(not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90 for p in value):
            raise ValueError("Invalid coordinates")
        return value


class Optimization(Input):
    start: tuple[float, float]
    stops: list[tuple[float, float]] = Field(min_length=1, max_length=50)
    end: tuple[float, float] | None = None

    @field_validator("start", "stops", "end")
    @classmethod
    def valid(cls, value):
        if value is None:
            return value
        points = value if isinstance(value, list) else [value]
        if any(not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90 for p in points):
            raise ValueError("Invalid coordinate")
        return value


class Assignment(Input):
    device_id: UUID
    route_id: UUID
    deviation_m: float = Field(default=150, ge=10, le=10000)
    deviation_seconds: int = Field(default=120, ge=1, le=3600)


class AlertUpdate(Input):
    state: Literal["acknowledged", "resolved"]
    notes: str = Field(default="", max_length=2000)


class KeyCreate(Named):
    scopes: list[Literal["read", "write"]] = Field(min_length=1, max_length=2)
    lifetime_days: int = Field(default=30, ge=1, le=365)


class SavedView(Named):
    configuration: dict


class Invite(Input):
    email: str = Field(max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    role: Literal["admin", "dispatcher", "operator", "viewer"]


class AcceptInvite(Input):
    token: str = Field(min_length=20, max_length=200)


class WorkspaceSettings(Input):
    retention_days: int = Field(ge=1, le=3650)
    offline_seconds: int = Field(ge=30, le=86400)
    moving_speed: float = Field(gt=0, le=30)
    stop_seconds: int = Field(ge=30, le=3600)


class RoleUpdate(Input):
    role: Literal["admin", "dispatcher", "operator", "viewer"]
