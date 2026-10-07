"""At-least-once transactional outbox processor; database effects commit before publication."""

import asyncio
import json
import logging
import signal
from datetime import datetime, timezone
from uuid import uuid4
from psycopg.types.json import Jsonb
from fastapi.encoders import jsonable_encoder
from geopulse.config import settings
from geopulse.db import pool, redis, one, many
from geopulse.main import emit
from geospatial import state
from geopulse.webhooks import enqueue
from worker.reconciliation import schedule_distance, reconcile_once

log = logging.getLogger("worker")
stopping = asyncio.Event()


async def alert(conn, wid, did, kind, recorded_at, severity="warning"):
    row = await one(
        conn,
        """INSERT INTO alerts(id,workspace_id,device_id,kind,severity,recorded_at)
      VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(device_id,kind) WHERE state IN ('open','acknowledged')
      DO NOTHING RETURNING *""",
        (uuid4(), wid, did, kind, severity, recorded_at),
    )
    if row:
        await emit(conn, wid, "alert.created", row)


async def resolve(conn, wid, did, kind):
    row = await one(
        conn,
        "UPDATE alerts SET state='resolved',resolved_at=now() WHERE device_id=%s AND kind=%s AND state<>'resolved' RETURNING *",
        (did, kind),
    )
    if row:
        await emit(conn, wid, "alert.updated", row)


async def geofences(conn, event):
    fences = await many(
        conn,
        """SELECT g.*,ST_Covers(g.geometry,%s::geography::geometry) covered,
      s.inside,s.entered_at,s.dwell_sent FROM geofences g LEFT JOIN geofence_state s
      ON s.geofence_id=g.id AND s.device_id=%s WHERE g.workspace_id=%s AND g.enabled""",
        (event["coordinates"], event["device_id"], event["workspace_id"]),
    )
    for fence in fences:
        kind = None
        entered_at = fence["entered_at"]
        dwell_sent = fence["dwell_sent"] or False
        if fence["covered"] and not fence["inside"]:
            kind, entered_at, dwell_sent = "enter", event["recorded_at"], False
        elif not fence["covered"] and fence["inside"]:
            kind, entered_at, dwell_sent = "exit", None, False
        elif (
            fence["covered"]
            and entered_at
            and not dwell_sent
            and (event["recorded_at"] - entered_at).total_seconds() >= fence["dwell_seconds"]
        ):
            kind, dwell_sent = "dwell", True
        await conn.execute(
            """INSERT INTO geofence_state(device_id,geofence_id,workspace_id,inside,entered_at,dwell_sent)
          VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(device_id,geofence_id) DO UPDATE
          SET inside=excluded.inside,entered_at=excluded.entered_at,dwell_sent=excluded.dwell_sent""",
            (event["device_id"], fence["id"], event["workspace_id"], fence["covered"], entered_at, dwell_sent),
        )
        if kind:
            gid = uuid4()
            await conn.execute(
                "INSERT INTO geofence_events(id,workspace_id,device_id,geofence_id,event_type,recorded_at,coordinates,location_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    gid,
                    event["workspace_id"],
                    event["device_id"],
                    fence["id"],
                    kind,
                    event["recorded_at"],
                    event["coordinates"],
                    event["id"],
                ),
            )
            await emit(
                conn,
                event["workspace_id"],
                "geofence." + kind,
                {
                    "id": gid,
                    "device_id": event["device_id"],
                    "geofence_id": fence["id"],
                    "recorded_at": event["recorded_at"],
                },
            )
            if kind == "dwell":
                await alert(
                    conn,
                    event["workspace_id"],
                    event["device_id"],
                    "geofence.dwell:" + str(fence["id"]),
                    event["recorded_at"],
                )
            elif kind == "exit":
                await resolve(conn, event["workspace_id"], event["device_id"], "geofence.dwell:" + str(fence["id"]))


async def route_checks(conn, event):
    row = await one(
        conn,
        """SELECT a.*,r.duration_s,r.geometry,
      ST_Distance(r.geometry,%s::geography) distance_from_route,
      ST_LineLocatePoint(r.geometry::geometry,%s::geography::geometry) progress,
      ST_Distance(ST_EndPoint(r.geometry::geometry)::geography,%s::geography) destination_distance
      FROM route_assignments a JOIN routes r ON r.id=a.route_id
      WHERE a.device_id=%s AND a.state IN ('assigned','active') FOR UPDATE OF a""",
        (event["coordinates"], event["coordinates"], event["coordinates"], event["device_id"]),
    )
    if not row:
        return
    deviating_since = row["deviating_since"]
    if row["distance_from_route"] > row["deviation_m"]:
        deviating_since = deviating_since or event["recorded_at"]
        if (event["recorded_at"] - deviating_since).total_seconds() >= row["deviation_seconds"]:
            await alert(conn, event["workspace_id"], event["device_id"], "route.deviation", event["recorded_at"])
    else:
        deviating_since = None
        await resolve(conn, event["workspace_id"], event["device_id"], "route.deviation")
    # Baseline ETA: remaining fraction of OSRM travel duration. Not traffic or predictive ETA.
    eta = max(0, (1 - row["progress"]) * row["duration_s"])
    assignment_state = "completed" if row["destination_distance"] <= 30 else "active"
    await conn.execute(
        "UPDATE route_assignments SET state=%s,deviating_since=%s,eta_seconds=%s WHERE id=%s",
        (assignment_state, deviating_since, eta, row["id"]),
    )


async def process_location(conn, payload):
    did = payload["device_id"]
    dev = await one(
        conn,
        "SELECT d.*,o.offline_seconds,o.stop_seconds,o.moving_speed FROM devices d JOIN organizations o ON o.id=d.workspace_id WHERE d.id=%s FOR UPDATE OF d",
        (did,),
    )
    event = await one(
        conn,
        "SELECT *,ST_X(coordinates::geometry) lng,ST_Y(coordinates::geometry) lat FROM location_events WHERE id=%s",
        (payload["location_id"],),
    )
    if not dev or not event:
        return "history.deleted", payload
    old = await one(
        conn,
        """SELECT *,ST_Distance(coordinates,%s::geography) delta_m,
      ST_Distance(coalesce(stationary_coordinates,coordinates),%s::geography) anchor_distance
      FROM device_status WHERE device_id=%s""",
        (event["coordinates"], event["coordinates"], did),
    )
    if old and old["recorded_at"] >= event["recorded_at"]:
        # Durable history, without reversing current operational state.
        await schedule_distance(conn, event)
        return "history.updated", {"device_id": did, "recorded_at": event["recorded_at"]}
    dt = (event["recorded_at"] - old["recorded_at"]).total_seconds() if old else 0
    continuous = old is not None and dt <= dev["offline_seconds"]
    delta = old["delta_m"] if continuous and old["delta_m"] <= 150 * dt + event["accuracy"] else 0
    stationary_since = event["recorded_at"]
    anchor = event["coordinates"]
    if continuous and event["speed"] <= dev["moving_speed"] and old["anchor_distance"] <= 30:
        stationary_since = old["stationary_since"] or event["recorded_at"]
        anchor = old["stationary_coordinates"] or old["coordinates"]
    stationary_duration = (event["recorded_at"] - stationary_since).total_seconds()
    age = (datetime.now(timezone.utc) - dev["last_seen"]).total_seconds()
    new_state = state(
        event["speed"], age, stationary_duration, dev["offline_seconds"], dev["moving_speed"], dev["stop_seconds"]
    )
    date = event["recorded_at"].date()
    today_distance = (old["distance_today_m"] if old and old["metric_date"] == date else 0) + delta
    await conn.execute(
        """INSERT INTO device_status(device_id,workspace_id,event_id,recorded_at,coordinates,speed,bearing,battery_level,
      state,stationary_since,stationary_coordinates,processed_at,distance_today_m,metric_date)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s)
      ON CONFLICT(device_id) DO UPDATE SET event_id=excluded.event_id,recorded_at=excluded.recorded_at,
      coordinates=excluded.coordinates,speed=excluded.speed,bearing=excluded.bearing,battery_level=excluded.battery_level,
      state=excluded.state,stationary_since=excluded.stationary_since,stationary_coordinates=excluded.stationary_coordinates,
      processed_at=now(),distance_today_m=excluded.distance_today_m,metric_date=excluded.metric_date""",
        (
            did,
            event["workspace_id"],
            event["event_id"],
            event["recorded_at"],
            event["coordinates"],
            event["speed"],
            event["bearing"],
            event["battery_level"],
            new_state,
            stationary_since,
            anchor,
            today_distance,
            date,
        ),
    )
    await conn.execute(
        """INSERT INTO historical_metrics VALUES (%s,%s,%s,%s) ON CONFLICT(workspace_id,device_id,date)
      DO UPDATE SET distance_m=historical_metrics.distance_m+excluded.distance_m""",
        (event["workspace_id"], did, date, delta),
    )
    trip = await one(conn, "SELECT * FROM trips WHERE device_id=%s AND ended_at IS NULL FOR UPDATE", (did,))
    if trip and not continuous:
        await conn.execute("UPDATE trips SET ended_at=%s WHERE id=%s", (old["recorded_at"], trip["id"]))
        await emit(conn, event["workspace_id"], "trip.completed", {"id": trip["id"], "device_id": did})
        trip = None
    if new_state == "moving" and not trip:
        tid = uuid4()
        await conn.execute(
            "INSERT INTO trips(id,workspace_id,device_id,started_at,max_speed) VALUES (%s,%s,%s,%s,%s)",
            (tid, event["workspace_id"], did, event["recorded_at"], event["speed"]),
        )
        await emit(conn, event["workspace_id"], "trip.started", {"id": tid, "device_id": did})
    elif trip:
        await conn.execute(
            "UPDATE trips SET distance_m=distance_m+%s,moving_seconds=moving_seconds+%s,idle_seconds=idle_seconds+%s,max_speed=greatest(max_speed,%s) WHERE id=%s",
            (delta, dt if new_state == "moving" else 0, dt if new_state != "moving" else 0, event["speed"], trip["id"]),
        )
        if new_state == "stopped":
            await conn.execute("UPDATE trips SET ended_at=%s WHERE id=%s", (event["recorded_at"], trip["id"]))
            await emit(conn, event["workspace_id"], "trip.completed", {"id": trip["id"], "device_id": did})
    if new_state == "stopped":
        await conn.execute(
            "INSERT INTO stops(id,workspace_id,device_id,arrived_at,coordinates) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(device_id) WHERE departed_at IS NULL DO NOTHING",
            (uuid4(), event["workspace_id"], did, stationary_since, anchor),
        )
    elif new_state == "moving" or (old and old["anchor_distance"] > 30):
        await conn.execute(
            "UPDATE stops SET departed_at=%s WHERE device_id=%s AND departed_at IS NULL", (event["recorded_at"], did)
        )
    await geofences(conn, event)
    await route_checks(conn, event)
    rules = await many(
        conn, "SELECT kind,threshold FROM alert_rules WHERE workspace_id=%s AND enabled", (event["workspace_id"],)
    )
    thresholds = {r["kind"]: r["threshold"] for r in rules}
    for kind, violated in (
        ("speed", event["speed"] > thresholds.get("speed", 30)),
        (
            "battery.low",
            event["battery_level"] is not None and event["battery_level"] < thresholds.get("battery.low", 15),
        ),
        ("idle.long", stationary_duration > thresholds.get("idle.long", 900)),
    ):
        if violated:
            await alert(conn, event["workspace_id"], did, kind, event["recorded_at"])
        else:
            await resolve(conn, event["workspace_id"], did, kind)
    await resolve(conn, event["workspace_id"], did, "device.offline")
    if not old or old["state"] == "offline":
        await emit(conn, event["workspace_id"], "device.online", {"device_id": did})
    return "location.updated", {
        "device_id": did,
        "name": dev["name"],
        "recorded_at": event["recorded_at"],
        "last_seen": dev["last_seen"],
        "lng": event["lng"],
        "lat": event["lat"],
        "state": new_state,
        "speed": event["speed"],
        "bearing": event["bearing"],
        "battery_level": event["battery_level"],
        "distance_today_m": today_distance,
    }


async def drain_once():
    async with pool.connection() as conn:
        # One ordered processor in MVP; sharding by device is documented, not claimed implemented.
        await conn.execute("SELECT pg_advisory_xact_lock(824132)")
        row = await one(conn, "SELECT * FROM outbox WHERE published_at IS NULL ORDER BY id LIMIT 1 FOR UPDATE")
        if not row:
            return False
        if not row["processed_at"]:
            topic, data = row["topic"], row["payload"]
            if topic == "location.received":
                topic, data = await process_location(conn, data)
            payload = {"id": str(row["id"]), "type": topic, "data": jsonable_encoder(data)}
            await conn.execute(
                "UPDATE outbox SET processed_at=now(),topic=%s,payload=%s WHERE id=%s",
                (topic, Jsonb(payload), row["id"]),
            )
            await enqueue(conn, row["workspace_id"], row["id"], payload)
        else:
            payload = row["payload"]
    # A Redis failure leaves the processed row pending. Consumers deduplicate outbox IDs.
    await redis.publish("workspace:" + str(row["workspace_id"]), json.dumps(payload))
    async with pool.connection() as conn:
        await conn.execute("UPDATE outbox SET published_at=now() WHERE id=%s", (row["id"],))
    return True


async def maintenance():
    async with pool.connection() as conn:
        await conn.execute("SELECT pg_advisory_xact_lock(824133)")
        offline = await many(
            conn,
            """UPDATE device_status s SET state='offline' FROM devices d,organizations o
          WHERE s.device_id=d.id AND d.workspace_id=o.id AND d.active AND s.state<>'offline'
          AND d.last_seen<now()-make_interval(secs=>o.offline_seconds) RETURNING s.workspace_id,s.device_id""",
        )
        for row in offline:
            await alert(conn, row["workspace_id"], row["device_id"], "device.offline", datetime.now(timezone.utc))
            await emit(conn, row["workspace_id"], "device.offline", row)
        # Bounded retention chunks; cascades remove geofence events tied to deleted GPS points.
        await conn.execute("""DELETE FROM location_events WHERE id IN (
          SELECT e.id FROM location_events e JOIN organizations o ON o.id=e.workspace_id
          WHERE e.recorded_at<now()-make_interval(days=>o.retention_days) LIMIT 1000)""")
        await conn.execute("DELETE FROM outbox WHERE published_at<now()-interval '7 days'")
        await conn.execute("DELETE FROM webhook_deliveries WHERE created_at<now()-interval '30 days'")
        # Apply the same workspace retention policy to derived history, not only raw GPS.
        for table, column in (
            ("trips", "started_at"),
            ("stops", "arrived_at"),
            ("geofence_events", "recorded_at"),
            ("alerts", "created_at"),
            ("location_snapshots", "created_at"),
        ):
            from psycopg import sql

            await conn.execute(
                sql.SQL(
                    "DELETE FROM {} h USING organizations o WHERE h.workspace_id=o.id AND h.{}<now()-make_interval(days=>o.retention_days)"
                ).format(sql.Identifier(table), sql.Identifier(column))
            )
        await conn.execute(
            "DELETE FROM historical_metrics h USING organizations o WHERE h.workspace_id=o.id AND h.date<current_date-o.retention_days"
        )
        await conn.execute(
            "DELETE FROM distance_reconciliation_jobs j USING organizations o WHERE j.workspace_id=o.id AND j.date<current_date-o.retention_days"
        )
        await conn.execute(
            "DELETE FROM device_status s USING organizations o WHERE s.workspace_id=o.id AND s.recorded_at<now()-make_interval(days=>o.retention_days)"
        )
    await redis.set("worker:heartbeat", datetime.now(timezone.utc).isoformat(), ex=30)


async def run():
    settings.validate()
    await pool.open(wait=True)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopping.set)
    next_maintenance = 0.0
    try:
        while not stopping.is_set():
            try:
                if loop.time() >= next_maintenance:
                    await maintenance()
                    await reconcile_once()
                    next_maintenance = loop.time() + 10
                if not await drain_once():
                    if await reconcile_once():
                        continue
                    try:
                        await asyncio.wait_for(stopping.wait(), timeout=0.1)
                    except asyncio.TimeoutError:
                        pass
            except Exception:
                log.exception("Worker iteration failed; durable outbox will retry")
                try:
                    await asyncio.wait_for(stopping.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass
    finally:
        await pool.close()
        await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
