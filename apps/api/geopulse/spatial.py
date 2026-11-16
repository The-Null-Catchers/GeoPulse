"""Bounded, workspace-scoped queries over persisted PostGIS data."""

import json
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from .db import pool, many, one
from .schemas import PolygonQuery
from .security import read_workspace

router = APIRouter(prefix="/api/v1/spatial", tags=["Spatial search"])


def page(rows, limit):
    return {"items": rows[:limit], "has_more": len(rows) > limit}


@router.get("/devices/closest")
async def closest_device(
    lat: float = Query(ge=-90, le=90, allow_inf_nan=False),
    lng: float = Query(ge=-180, le=180, allow_inf_nan=False),
    radius: float = Query(10000, gt=0, le=100000, allow_inf_nan=False),
    ws=Depends(read_workspace),
):
    """Closest active device within the bounded radius, using spheroidal meter distance."""
    async with pool.connection() as conn:
        return await one(
            conn,
            """SELECT d.id,d.name,s.recorded_at,
                      ST_X(s.coordinates::geometry) lng,ST_Y(s.coordinates::geometry) lat,
                      ST_Distance(s.coordinates,q.p) distance_m
               FROM device_status s JOIN devices d ON d.id=s.device_id
               CROSS JOIN (SELECT ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography p) q
               WHERE s.workspace_id=%s AND d.active AND ST_DWithin(s.coordinates,q.p,%s)
               ORDER BY distance_m,d.id LIMIT 1""",
            (lng, lat, ws["id"], radius),
        )


@router.post("/devices/in-polygon")
async def devices_in_polygon(
    body: PolygonQuery,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100000),
    ws=Depends(read_workspace),
):
    """Active latest snapshots covered by a WGS84 polygon, including its boundary."""
    async with pool.connection() as conn:
        geometry = await one(
            conn, "SELECT ST_SetSRID(ST_GeomFromGeoJSON(%s),4326) g", (json.dumps(body.geometry),)
        )
        valid = await one(conn, "SELECT ST_IsValid(%s::geometry) valid", (geometry["g"],))
        if not valid["valid"]:
            raise HTTPException(422, "Invalid polygon topology")
        rows = await many(
            conn,
            """SELECT d.id,d.name,s.recorded_at,
                      ST_X(s.coordinates::geometry) lng,ST_Y(s.coordinates::geometry) lat
               FROM device_status s JOIN devices d ON d.id=s.device_id
               WHERE s.workspace_id=%s AND d.active
                 AND ST_Covers(%s::geometry,s.coordinates::geometry)
               ORDER BY d.id LIMIT %s OFFSET %s""",
            (ws["id"], geometry["g"], limit + 1, offset),
        )
    return page(rows, limit)


@router.get("/devices/near-route")
async def devices_near_route(
    route_id: UUID,
    radius: float = Query(150, gt=0, le=100000, allow_inf_nan=False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100000),
    ws=Depends(read_workspace),
):
    async with pool.connection() as conn:
        route = await one(conn, "SELECT geometry FROM routes WHERE id=%s AND workspace_id=%s", (route_id, ws["id"]))
        if not route:
            raise HTTPException(404, "Route not found")
        rows = await many(
            conn,
            """SELECT d.id,d.name,s.recorded_at,
                      ST_X(s.coordinates::geometry) lng,ST_Y(s.coordinates::geometry) lat,
                      ST_Distance(s.coordinates,%s::geography) distance_m
               FROM device_status s JOIN devices d ON d.id=s.device_id
               WHERE s.workspace_id=%s AND d.active AND ST_DWithin(s.coordinates,%s::geography,%s)
               ORDER BY distance_m,d.id LIMIT %s OFFSET %s""",
            (route["geometry"], ws["id"], route["geometry"], radius, limit + 1, offset),
        )
    return page(rows, limit)


@router.get("/geofences/containing")
async def containing_geofences(
    lat: float = Query(ge=-90, le=90, allow_inf_nan=False),
    lng: float = Query(ge=-180, le=180, allow_inf_nan=False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100000),
    ws=Depends(read_workspace),
):
    async with pool.connection() as conn:
        rows = await many(
            conn,
            """SELECT id,name,ST_AsGeoJSON(geometry)::json geometry FROM geofences
               WHERE workspace_id=%s AND enabled AND ST_Covers(geometry,ST_SetSRID(ST_MakePoint(%s,%s),4326))
               ORDER BY id LIMIT %s OFFSET %s""",
            (ws["id"], lng, lat, limit + 1, offset),
        )
    return page(rows, limit)


@router.get("/stops/nearby")
async def nearby_stops(
    start: datetime,
    end: datetime,
    lat: float = Query(ge=-90, le=90, allow_inf_nan=False),
    lng: float = Query(ge=-180, le=180, allow_inf_nan=False),
    radius: float = Query(1000, gt=0, le=100000, allow_inf_nan=False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100000),
    ws=Depends(read_workspace),
):
    """Stops whose arrival is in the inclusive UTC range, at most 31 days."""
    if start.tzinfo is None or end.tzinfo is None or end <= start or end - start > timedelta(days=31):
        raise HTTPException(422, "Timezone-aware range of at most 31 days required")
    async with pool.connection() as conn:
        rows = await many(
            conn,
            """SELECT s.id,s.device_id,d.name device_name,s.arrived_at,s.departed_at,
                      ST_X(s.coordinates::geometry) lng,ST_Y(s.coordinates::geometry) lat,
                      ST_Distance(s.coordinates,q.p) distance_m
               FROM stops s JOIN devices d ON d.id=s.device_id
               CROSS JOIN (SELECT ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography p) q
               WHERE s.workspace_id=%s AND s.arrived_at BETWEEN %s AND %s
                 AND ST_DWithin(s.coordinates,q.p,%s)
               ORDER BY distance_m,s.id LIMIT %s OFFSET %s""",
            (lng, lat, ws["id"], start, end, radius, limit + 1, offset),
        )
    return page(rows, limit)
