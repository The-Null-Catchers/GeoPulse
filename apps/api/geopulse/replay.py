"""Keyset-paged historical points and persisted operational timeline events."""

from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from .db import pool, one, many
from .security import workspace

router = APIRouter(prefix="/api/v1/devices/{device_id}/replay", tags=["Historical replay"])


def validate_range(start, end, after_time, after_id):
    if start.tzinfo is None or end.tzinfo is None or end <= start or end - start > timedelta(days=7):
        raise HTTPException(422, "Timezone-aware range of at most 7 days required")
    if (after_time is None) != (after_id is None):
        raise HTTPException(422, "Cursor time and ID must be supplied together")
    if after_time is not None and (after_time.tzinfo is None or not start <= after_time <= end):
        raise HTTPException(422, "Timezone-aware cursor within the requested range required")


async def owned_device(conn, device_id, workspace_id):
    if not await one(conn, "SELECT id FROM devices WHERE id=%s AND workspace_id=%s", (device_id, workspace_id)):
        raise HTTPException(404, "Device not found")


def paged(rows, limit, id_field="id"):
    items = rows[:limit]
    cursor = None
    if len(rows) > limit:
        cursor = {"recorded_at": items[-1]["recorded_at"], "id": items[-1][id_field]}
    return {"items": items, "next_cursor": cursor}


@router.get("/points")
async def replay_points(
    device_id: UUID,
    start: datetime,
    end: datetime,
    limit: int = Query(1000, ge=1, le=5000),
    after_time: datetime | None = None,
    after_id: UUID | None = None,
    ws=Depends(workspace),
):
    validate_range(start, end, after_time, after_id)
    async with pool.connection() as conn:
        await owned_device(conn, device_id, ws["id"])
        rows = await many(
            conn,
            """SELECT event_id,recorded_at,speed,bearing,accuracy,battery_level,
                      ST_X(coordinates::geometry) lng,ST_Y(coordinates::geometry) lat
               FROM location_events WHERE workspace_id=%s AND device_id=%s AND recorded_at BETWEEN %s AND %s
                 AND (%s::timestamptz IS NULL OR (recorded_at,event_id)>(%s::timestamptz,%s::uuid))
               ORDER BY recorded_at,event_id LIMIT %s""",
            (ws["id"], device_id, start, end, after_time, after_time, after_id, limit + 1),
        )
    return paged(rows, limit, "event_id")


@router.get("/events")
async def replay_events(
    device_id: UUID,
    start: datetime,
    end: datetime,
    limit: int = Query(500, ge=1, le=1000),
    after_time: datetime | None = None,
    after_id: str | None = Query(None, max_length=100, pattern=r"^[a-z.]+:[0-9a-f-]{36}$"),
    ws=Depends(workspace),
):
    validate_range(start, end, after_time, after_id)
    async with pool.connection() as conn:
        await owned_device(conn, device_id, ws["id"])
        # Every union arm scopes the resource before joining related rows. Events have
        # stable composite IDs because one stop has both arrival and departure events.
        rows = await many(
            conn,
            """WITH events AS (
                 SELECT 'stop.arrival:'||s.id id,'stop.arrival' kind,s.arrived_at recorded_at,
                        'Stop started' label,ST_X(s.coordinates::geometry) lng,ST_Y(s.coordinates::geometry) lat,
                        s.arrived_at location_recorded_at,NULL::double precision duration_seconds,NULL::text severity
                 FROM stops s WHERE s.workspace_id=%(wid)s AND s.device_id=%(did)s
                   AND s.arrived_at BETWEEN %(start)s AND %(end)s
                 UNION ALL
                 SELECT 'stop.departure:'||s.id,'stop.departure',s.departed_at,'Stop ended',
                        ST_X(s.coordinates::geometry),ST_Y(s.coordinates::geometry),s.arrived_at,
                        extract(epoch FROM s.departed_at-s.arrived_at),NULL::text
                 FROM stops s WHERE s.workspace_id=%(wid)s AND s.device_id=%(did)s
                   AND s.departed_at BETWEEN %(start)s AND %(end)s
                 UNION ALL
                 SELECT 'geofence.'||e.event_type||':'||e.id,'geofence.'||e.event_type,e.recorded_at,g.name,
                        ST_X(e.coordinates::geometry),ST_Y(e.coordinates::geometry),e.recorded_at,NULL,NULL
                 FROM geofence_events e JOIN geofences g ON g.id=e.geofence_id AND g.workspace_id=e.workspace_id
                 WHERE e.workspace_id=%(wid)s AND e.device_id=%(did)s
                   AND e.recorded_at BETWEEN %(start)s AND %(end)s
                 UNION ALL
                 SELECT 'alert.created:'||a.id,'alert.created',coalesce(a.recorded_at,a.created_at),a.kind,
                        ST_X(p.coordinates::geometry),ST_Y(p.coordinates::geometry),p.recorded_at,NULL,a.severity
                 FROM alerts a LEFT JOIN LATERAL (
                   SELECT coordinates,recorded_at FROM location_events l
                   WHERE l.workspace_id=a.workspace_id AND l.device_id=a.device_id
                     AND l.recorded_at<=coalesce(a.recorded_at,a.created_at)
                   ORDER BY l.recorded_at DESC,l.event_id DESC LIMIT 1
                 ) p ON true
                 WHERE a.workspace_id=%(wid)s AND a.device_id=%(did)s
                   AND coalesce(a.recorded_at,a.created_at) BETWEEN %(start)s AND %(end)s
               ) SELECT * FROM events
                 WHERE (%(after_time)s::timestamptz IS NULL
                        OR (recorded_at,id)>(%(after_time)s::timestamptz,%(after_id)s::text))
                 ORDER BY recorded_at,id LIMIT %(limit)s""",
            {"wid": ws["id"], "did": device_id, "start": start, "end": end,
             "after_time": after_time, "after_id": after_id, "limit": limit + 1},
        )
    return paged(rows, limit)
