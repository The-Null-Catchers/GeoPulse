"""Retry-safe daily distance repair; never rewind live state or replay operational alerts."""

from datetime import datetime, time, timedelta, timezone

from geopulse.db import pool, one
from geopulse.main import emit


async def schedule_distance(conn, event):
    # A new sample changes its incoming segment and its successor's incoming segment.
    # Valid segments span at most offline_seconds (at most one day), hence two UTC days suffice.
    day = event["recorded_at"].astimezone(timezone.utc).date()
    for affected in (day, day + timedelta(days=1)):
        await conn.execute(
            """INSERT INTO distance_reconciliation_jobs(workspace_id,device_id,date)
               VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""",
            (event["workspace_id"], event["device_id"], affected),
        )


async def reconcile_once():
    async with pool.connection() as conn:
        # Match the processor lock order: advisory lock, device, then job. Ingestion also locks the device.
        await conn.execute("SELECT pg_advisory_xact_lock(824132)")
        job = await one(
            conn,
            """SELECT j.* FROM distance_reconciliation_jobs j
               WHERE NOT EXISTS (SELECT 1 FROM outbox o WHERE o.workspace_id=j.workspace_id
                 AND o.topic='location.received' AND o.processed_at IS NULL
                 AND o.payload->>'device_id'=j.device_id::text)
               ORDER BY j.requested_at,j.device_id,j.date LIMIT 1""",
        )
        if not job:
            return False
        dev = await one(
            conn,
            """SELECT d.id,o.offline_seconds,o.retention_days FROM devices d
               JOIN organizations o ON o.id=d.workspace_id
               WHERE d.id=%s AND d.workspace_id=%s FOR UPDATE OF d""",
            (job["device_id"], job["workspace_id"]),
        )
        if not dev:
            return False  # Concurrent device erasure cascades the job.
        if not await one(
            conn,
            "SELECT date FROM distance_reconciliation_jobs WHERE workspace_id=%s AND device_id=%s AND date=%s FOR UPDATE",
            (job["workspace_id"], job["device_id"], job["date"]),
        ):
            return False  # History erasure may have removed this job while the device lock was held.
        # Admission may have queued more points while we waited for the device lock.
        if await one(
            conn,
            """SELECT id FROM outbox WHERE workspace_id=%s AND topic='location.received'
               AND processed_at IS NULL AND payload->>'device_id'=%s LIMIT 1""",
            (job["workspace_id"], str(job["device_id"])),
        ):
            return False
        day = job["date"]
        start = datetime.combine(day, time.min, timezone.utc)
        end = start + timedelta(days=1)
        retention_cutoff = datetime.now(timezone.utc) - timedelta(days=dev["retention_days"])
        if day >= retention_cutoff.date():
            await conn.execute("SET LOCAL statement_timeout='10s'")
            result = await one(
                conn,
                """WITH samples AS (
                     SELECT DISTINCT ON (recorded_at) recorded_at,coordinates,accuracy
                     FROM location_events WHERE workspace_id=%s AND device_id=%s
                       AND recorded_at >= %s AND recorded_at < %s
                     ORDER BY recorded_at,event_id
                   ), segments AS (
                     SELECT *,lag(coordinates) OVER w previous_coordinates,
                       extract(epoch FROM recorded_at-lag(recorded_at) OVER w) dt
                     FROM samples WINDOW w AS (ORDER BY recorded_at)
                   ), distances AS (
                     SELECT *,ST_Distance(coordinates,previous_coordinates) distance_m FROM segments
                   ) SELECT coalesce(sum(CASE WHEN dt>0 AND dt<=%s
                       AND distance_m<=150*dt+accuracy THEN distance_m ELSE 0 END),0) distance_m
                     FROM distances WHERE recorded_at >= %s""",
                (
                    job["workspace_id"], job["device_id"],
                    max(start - timedelta(seconds=dev["offline_seconds"]), retention_cutoff), end,
                    dev["offline_seconds"], start,
                ),
            )
            distance = result["distance_m"]
            await conn.execute(
                """INSERT INTO historical_metrics(workspace_id,device_id,date,distance_m)
                   VALUES (%s,%s,%s,%s) ON CONFLICT(workspace_id,device_id,date)
                   DO UPDATE SET distance_m=excluded.distance_m""",
                (job["workspace_id"], job["device_id"], day, distance),
            )
            await conn.execute(
                """UPDATE device_status SET distance_today_m=%s
                   WHERE workspace_id=%s AND device_id=%s AND metric_date=%s""",
                (distance, job["workspace_id"], job["device_id"], day),
            )
            await emit(conn, job["workspace_id"], "metrics.updated", {
                "device_id": job["device_id"], "date": day, "distance_m": distance,
            })
        await conn.execute(
            "DELETE FROM distance_reconciliation_jobs WHERE workspace_id=%s AND device_id=%s AND date=%s",
            (job["workspace_id"], job["device_id"], day),
        )
    return True
