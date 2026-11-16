"""Bounded daily distance aggregates from persisted geospatial metrics."""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from .db import pool, one, many
from .security import workspace, require

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])


@router.post("/distance/recalculate", status_code=202)
async def recalculate_distance(start: date, end: date, device_id: UUID, ws=Depends(require("admin"))):
    if end < start or (end - start).days >= 90:
        raise HTTPException(422, "An inclusive range of at most 90 UTC days is required")
    async with pool.connection() as conn:
        dev = await one(
            conn,
            """SELECT o.retention_days FROM devices d JOIN organizations o ON o.id=d.workspace_id
               WHERE d.workspace_id=%s AND d.id=%s FOR UPDATE OF d""",
            (ws["id"], device_id),
        )
        if not dev:
            raise HTTPException(404, "Device not found")
        today = datetime.now(timezone.utc).date()
        if start < today - timedelta(days=dev["retention_days"]) or end > today:
            raise HTTPException(422, "Range must be inside retained history and cannot extend into future UTC days")
        # Include a successor day to repair segments that end across midnight.
        await conn.execute(
            """INSERT INTO distance_reconciliation_jobs(workspace_id,device_id,date)
               SELECT %s::uuid,%s::uuid,generate_series(%s::date,%s::date,interval '1 day')::date
               ON CONFLICT DO NOTHING""",
            (ws["id"], device_id, start, end + timedelta(days=1)),
        )
        from .main import audit

        await audit(conn, ws, "device.distance_recalculation_requested", device_id)
    return {"device_id": device_id, "start": start, "end": end + timedelta(days=1), "state": "queued"}


@router.get("/distance")
async def daily_distance(start: date, end: date, device_id: UUID | None = None, ws=Depends(workspace)):
    if end < start or (end - start).days >= 90:
        raise HTTPException(422, "An inclusive range of at most 90 UTC days is required")
    async with pool.connection() as conn:
        if device_id and not await one(
            conn, "SELECT id FROM devices WHERE workspace_id=%s AND id=%s", (ws["id"], device_id)
        ):
            raise HTTPException(404, "Device not found")
        return await many(
            conn,
            """WITH days AS (SELECT generate_series(%s::date,%s::date,interval '1 day')::date date),
               metrics AS (SELECT date,sum(distance_m) distance_m FROM historical_metrics
                 WHERE workspace_id=%s AND (%s::uuid IS NULL OR device_id=%s) AND date BETWEEN %s AND %s
                 GROUP BY date),
               pending AS (SELECT date,count(*) pending_devices FROM distance_reconciliation_jobs
                 WHERE workspace_id=%s AND (%s::uuid IS NULL OR device_id=%s) AND date BETWEEN %s AND %s
                 GROUP BY date)
               SELECT d.date,coalesce(m.distance_m,0) distance_m,coalesce(p.pending_devices,0) pending_devices
               FROM days d LEFT JOIN metrics m USING(date) LEFT JOIN pending p USING(date) ORDER BY d.date""",
            (start, end, ws["id"], device_id, device_id, start, end,
             ws["id"], device_id, device_id, start, end),
        )
