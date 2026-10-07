import asyncio
import csv
import io
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, Query
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from psycopg.types.json import Jsonb
from psycopg import sql
from psycopg.errors import UniqueViolation, ForeignKeyViolation
from .config import settings
from .db import pool, redis, one, many
from .security import (
    passwords,
    digest,
    opaque,
    access_token,
    verify_password,
    user,
    workspace,
    require,
    device,
    rate_limit,
)
from .schemas import (
    Registration,
    Login,
    Refresh,
    Named,
    DeviceCreate,
    DeviceUpdate,
    Location,
    Batch,
    Fence,
    RouteCreate,
    Optimization,
    Assignment,
    AlertUpdate,
    KeyCreate,
    SavedView,
    Invite,
    AcceptInvite,
)
from geospatial import optimize
from .spatial import router as spatial_router
from .replay import router as replay_router
from .analytics import router as analytics_router

logger = logging.getLogger("geopulse")
logging.basicConfig(level=logging.INFO, format="%(message)s")


@asynccontextmanager
async def lifespan(app):
    settings.validate()
    await pool.open(wait=True)
    await redis.ping()
    yield
    await pool.close()
    await redis.aclose()


app = FastAPI(title="GeoPulse API", version="0.1.0", lifespan=lifespan)
app.include_router(spatial_router)
app.include_router(replay_router)
app.include_router(analytics_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Workspace-ID"],
)


@app.middleware("http")
async def headers(request, call_next):
    rid = str(uuid4())
    started = time.perf_counter()
    response = await call_next(request)
    response.headers.update(
        {
            "X-Request-ID": rid,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
        }
    )
    logger.info(
        json.dumps(
            {
                "request_id": rid,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )
    )
    return response


@app.exception_handler(UniqueViolation)
async def conflict(request, exc):
    return Response(status_code=409, content='{"detail":"Resource already exists"}', media_type="application/json")


@app.exception_handler(ForeignKeyViolation)
async def foreign_key(request, exc):
    return Response(
        status_code=404, content='{"detail":"Related resource not found in workspace"}', media_type="application/json"
    )


async def audit(conn, ws, action, resource):
    await conn.execute(
        "INSERT INTO audit_logs(id,workspace_id,user_id,action,resource_id) VALUES (%s,%s,%s,%s,%s)",
        (uuid4(), ws["id"], ws["user_id"], action, resource),
    )


async def emit(conn, workspace_id, topic, payload):
    return await one(
        conn,
        "INSERT INTO outbox(workspace_id,topic,payload) VALUES (%s,%s,%s) RETURNING id",
        (workspace_id, topic, Jsonb(jsonable_encoder(payload))),
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "geopulse-api"}


@app.get("/ready")
async def ready():
    async with pool.connection() as conn:
        await conn.execute("SELECT 1 FROM schema_migrations LIMIT 1")
    await redis.ping()
    return {"status": "ready"}


async def session(conn, uid, response, family=None):
    token = opaque("gpr")
    await conn.execute(
        "INSERT INTO refresh_sessions(id,user_id,secret_hash,family_id,expires_at) VALUES (%s,%s,%s,%s,%s)",
        (uuid4(), uid, digest(token), family or uuid4(), datetime.now(timezone.utc) + timedelta(days=30)),
    )
    response.set_cookie(
        "gp_refresh",
        token,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "true") == "true",
        samesite="strict",
        path="/api/v1/auth",
        max_age=30 * 86400,
    )
    return {"access_token": access_token(uid), "refresh_token": token, "token_type": "bearer"}


@app.post("/api/v1/auth/register", status_code=201)
async def register(body: Registration, request: Request, response: Response):
    await rate_limit(f"register:{request.client.host if request.client else 'unknown'}", 10, 3600)
    uid, wid = uuid4(), uuid4()
    hashed = await asyncio.to_thread(passwords.hash, body.password)
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO users(id,email,name,password_hash) VALUES (%s,%s,%s,%s)",
            (uid, body.email.lower(), body.name, hashed),
        )
        await conn.execute("INSERT INTO organizations(id,name) VALUES (%s,%s)", (wid, body.organization))
        await conn.execute("INSERT INTO memberships VALUES (%s,%s,'owner')", (wid, uid))
        tokens = await session(conn, uid, response)
        await audit(conn, {"id": wid, "user_id": uid}, "organization.created", wid)
    return {**tokens, "workspace_id": wid, "user_id": uid}


@app.post("/api/v1/auth/login")
async def login(body: Login, request: Request, response: Response):
    await rate_limit(f"login:{request.client.host if request.client else 'unknown'}", 30, 300)
    async with pool.connection() as conn:
        row = await one(conn, "SELECT * FROM users WHERE email=%s", (body.email.lower(),))
        if not row or not await asyncio.to_thread(verify_password, body.password, row["password_hash"]):
            raise HTTPException(401, "Invalid credentials")
        tokens = await session(conn, row["id"], response)
        workspaces = await many(
            conn,
            "SELECT o.id,o.name,m.role FROM memberships m JOIN organizations o ON o.id=m.workspace_id WHERE user_id=%s",
            (row["id"],),
        )
    return {**tokens, "workspaces": workspaces, "user_id": row["id"]}


def cookie_origin(request):
    origin = request.headers.get("origin")
    if origin and origin not in settings.origins:
        raise HTTPException(403, "Origin denied")


@app.post("/api/v1/auth/refresh")
async def refresh(body: Refresh, request: Request, response: Response):
    cookie_origin(request)
    token = body.refresh_token or request.cookies.get("gp_refresh", "")
    reuse = False
    async with pool.connection() as conn:
        row = await one(conn, "SELECT * FROM refresh_sessions WHERE secret_hash=%s FOR UPDATE", (digest(token),))
        if not row or row["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(401, "Refresh expired")
        if row["revoked_at"]:
            await conn.execute("UPDATE refresh_sessions SET revoked_at=now() WHERE family_id=%s", (row["family_id"],))
            reuse = True
        else:
            await conn.execute("UPDATE refresh_sessions SET revoked_at=now() WHERE id=%s", (row["id"],))
            result = await session(conn, row["user_id"], response, row["family_id"])
    if reuse:
        raise HTTPException(401, "Refresh reuse detected; session family revoked")
    return result


@app.post("/api/v1/auth/logout", status_code=204)
async def logout(body: Refresh, request: Request, response: Response):
    cookie_origin(request)
    token = body.refresh_token or request.cookies.get("gp_refresh", "")
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE refresh_sessions SET revoked_at=now() WHERE family_id IN (SELECT family_id FROM refresh_sessions WHERE secret_hash=%s)",
            (digest(token),),
        )
    response.delete_cookie("gp_refresh", path="/api/v1/auth")


@app.get("/api/v1/workspaces")
async def workspaces(uid=Depends(user)):
    async with pool.connection() as conn:
        return await many(
            conn,
            "SELECT o.*,m.role FROM organizations o JOIN memberships m ON m.workspace_id=o.id WHERE user_id=%s",
            (uid,),
        )


@app.post("/api/v1/workspaces", status_code=201)
async def new_workspace(body: Named, uid=Depends(user)):
    wid = uuid4()
    async with pool.connection() as conn:
        await conn.execute("INSERT INTO organizations(id,name) VALUES (%s,%s)", (wid, body.name))
        await conn.execute("INSERT INTO memberships VALUES (%s,%s,'owner')", (wid, uid))
        await audit(conn, {"id": wid, "user_id": uid}, "organization.created", wid)
    return {"id": wid, "name": body.name}


@app.post("/api/v1/invitations", status_code=201)
async def invite(body: Invite, ws=Depends(require("admin"))):
    token, iid = opaque("gpi"), uuid4()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO invitations(id,workspace_id,email,role,secret_hash,expires_at) VALUES (%s,%s,%s,%s,%s,now()+interval '7 days')",
            (iid, ws["id"], body.email.lower(), body.role, digest(token)),
        )
        await audit(conn, ws, "invitation.created", iid)
    return {
        "id": iid,
        "token": token,
        "delivery": "Share this one-time invitation with the recipient; email transport is not configured.",
    }


@app.post("/api/v1/invitations/accept")
async def accept_invite(body: AcceptInvite, uid=Depends(user)):
    async with pool.connection() as conn:
        row = await one(
            conn,
            "SELECT i.* FROM invitations i JOIN users u ON u.email=i.email WHERE i.secret_hash=%s AND u.id=%s AND i.expires_at>now() AND i.accepted_at IS NULL FOR UPDATE OF i",
            (digest(body.token), uid),
        )
        if not row:
            raise HTTPException(404, "Valid invitation not found")
        await conn.execute(
            "INSERT INTO memberships VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (row["workspace_id"], uid, row["role"])
        )
        await conn.execute("UPDATE invitations SET accepted_at=now() WHERE id=%s", (row["id"],))
        await audit(conn, {"id": row["workspace_id"], "user_id": uid}, "invitation.accepted", row["id"])
    return {"workspace_id": row["workspace_id"]}


@app.get("/api/v1/devices")
async def devices(
    ws=Depends(workspace),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    team_id: UUID | None = None,
):
    async with pool.connection() as conn:
        return await many(
            conn,
            """SELECT d.id,d.name,d.device_type,d.active,d.team_id,d.driver_id,d.vehicle_id,d.last_seen,
          s.recorded_at,s.speed,s.bearing,s.battery_level,
          CASE WHEN s.metric_date=(now() AT TIME ZONE 'UTC')::date THEN s.distance_today_m ELSE 0 END distance_today_m,
          CASE WHEN NOT d.active THEN 'unknown' WHEN d.last_seen IS NULL THEN 'unknown'
               WHEN d.last_seen<now()-make_interval(secs=>o.offline_seconds) THEN 'offline' ELSE coalesce(s.state,'online') END state,
          ST_X(s.coordinates::geometry) lng, ST_Y(s.coordinates::geometry) lat
          FROM devices d JOIN organizations o ON o.id=d.workspace_id LEFT JOIN device_status s ON s.device_id=d.id
          WHERE d.workspace_id=%s AND (%s::uuid IS NULL OR d.team_id=%s)
          AND (%s::text IS NULL OR CASE WHEN d.last_seen IS NULL THEN 'unknown'
            WHEN d.last_seen<now()-make_interval(secs=>o.offline_seconds) THEN 'offline' ELSE coalesce(s.state,'online') END=%s)
          ORDER BY d.name,d.id LIMIT %s OFFSET %s""",
            (ws["id"], team_id, team_id, status, status, limit, offset),
        )


@app.post("/api/v1/devices", status_code=201)
async def create_device(body: DeviceCreate, ws=Depends(require("dispatcher"))):
    did, token = uuid4(), opaque("gpd")
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO devices(id,workspace_id,name,device_type,token_hash,team_id,driver_id,vehicle_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (did, ws["id"], body.name, body.device_type, digest(token), body.team_id, body.driver_id, body.vehicle_id),
        )
        await audit(conn, ws, "device.created", did)
    return {"id": did, "name": body.name, "token": token}


@app.patch("/api/v1/devices/{device_id}")
async def update_device(device_id: UUID, body: DeviceUpdate, ws=Depends(require("dispatcher"))):
    async with pool.connection() as conn:
        row = await one(
            conn,
            "UPDATE devices SET active=%s WHERE id=%s AND workspace_id=%s RETURNING id,active",
            (body.active, device_id, ws["id"]),
        )
        if not row:
            raise HTTPException(404, "Device not found")
        await audit(conn, ws, "device.tracking_changed", device_id)
    return row


@app.post("/api/v1/devices/{device_id}/rotate-token")
async def rotate_device_token(device_id: UUID, ws=Depends(require("admin"))):
    token = opaque("gpd")
    async with pool.connection() as conn:
        row = await one(
            conn,
            "UPDATE devices SET token_hash=%s WHERE id=%s AND workspace_id=%s RETURNING id",
            (digest(token), device_id, ws["id"]),
        )
        if not row:
            raise HTTPException(404, "Device not found")
        await audit(conn, ws, "device.token_rotated", device_id)
    return {"id": device_id, "token": token}


@app.delete("/api/v1/devices/{device_id}/history", status_code=204)
async def delete_history(device_id: UUID, ws=Depends(require("admin"))):
    async with pool.connection() as conn:
        row = await one(
            conn, "SELECT id FROM devices WHERE id=%s AND workspace_id=%s FOR UPDATE", (device_id, ws["id"])
        )
        if not row:
            raise HTTPException(404, "Device not found")
        await conn.execute(
            "DELETE FROM webhook_deliveries WHERE device_id=%s AND workspace_id=%s", (device_id, ws["id"])
        )
        await conn.execute("DELETE FROM location_events WHERE device_id=%s", (device_id,))
        for table in ("device_status", "trips", "stops", "geofence_state", "geofence_events", "historical_metrics", "alerts", "distance_reconciliation_jobs"):
            await conn.execute(
                sql.SQL("DELETE FROM {} WHERE device_id=%s").format(sql.Identifier(table)), (device_id,)
            )  # table names fixed above
        await conn.execute(
            "DELETE FROM outbox WHERE workspace_id=%s AND coalesce(payload->>'device_id',payload->'data'->>'device_id')=%s",
            (ws["id"], str(device_id)),
        )
        await conn.execute("UPDATE devices SET last_seen=NULL WHERE id=%s", (device_id,))
        await audit(conn, ws, "device.history_deleted", device_id)
        await emit(conn, ws["id"], "device.history_deleted", {"device_id": device_id})


async def ingest(points, dev):
    inserted, duplicates, filtered = 0, 0, 0
    async with pool.connection() as conn:
        # Serializes concurrent batches and workers for a device. Active flag is rechecked under the lock.
        locked = await one(conn, "SELECT active FROM devices WHERE id=%s FOR UPDATE", (dev["id"],))
        if not locked or not locked["active"]:
            raise HTTPException(401, "Tracking disabled")
        for p in sorted(points, key=lambda p: (p.recorded_at, str(p.event_id))):
            if p.accuracy > 200 or p.recorded_at < datetime.now(timezone.utc) - timedelta(days=dev["retention_days"]):
                filtered += 1
                continue
            lid = uuid4()
            row = await one(
                conn,
                """INSERT INTO location_events(id,workspace_id,device_id,event_id,recorded_at,
              coordinates,altitude,speed,bearing,accuracy,battery_level,source)
              VALUES (%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,%s,%s,%s,%s,%s,%s)
              ON CONFLICT(device_id,event_id) DO NOTHING RETURNING id""",
                (
                    lid,
                    dev["workspace_id"],
                    dev["id"],
                    p.event_id,
                    p.recorded_at,
                    p.lng,
                    p.lat,
                    p.altitude,
                    p.speed,
                    p.bearing,
                    p.accuracy,
                    p.battery_level,
                    p.source,
                ),
            )
            if row:
                inserted += 1
                await emit(conn, dev["workspace_id"], "location.received", {"location_id": lid, "device_id": dev["id"]})
            else:
                duplicates += 1
        await conn.execute("UPDATE devices SET last_seen=now() WHERE id=%s", (dev["id"],))
    return {"inserted": inserted, "duplicates": duplicates, "filtered": filtered}


@app.post("/api/v1/locations", status_code=202)
async def location(body: Location, dev=Depends(device)):
    return await ingest([body], dev)


@app.post("/api/v1/locations/batch", status_code=202)
async def batch(body: Batch, dev=Depends(device)):
    return await ingest(body.points, dev)


@app.post("/api/v1/devices/heartbeat")
async def heartbeat(dev=Depends(device)):
    async with pool.connection() as conn:
        row = await one(conn, "UPDATE devices SET last_seen=now() WHERE id=%s AND active RETURNING id", (dev["id"],))
        if not row:
            raise HTTPException(401, "Tracking disabled")
    return {"received_at": datetime.now(timezone.utc)}


@app.get("/api/v1/devices/nearby")
async def nearby(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    radius: float = Query(default=1000, gt=0, le=100000),
    ws=Depends(workspace),
):
    async with pool.connection() as conn:
        return await many(
            conn,
            """SELECT d.id,d.name,ST_Distance(s.coordinates,ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) distance_m
         FROM device_status s JOIN devices d ON d.id=s.device_id WHERE s.workspace_id=%s AND d.active
         AND ST_DWithin(s.coordinates,ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,%s)
         ORDER BY distance_m LIMIT 100""",
            (lng, lat, ws["id"], lng, lat, radius),
        )


@app.get("/api/v1/devices/{device_id}/history")
async def history(
    device_id: UUID,
    start: datetime,
    end: datetime,
    ws=Depends(workspace),
    limit: int = Query(5000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
):
    if start.tzinfo is None or end.tzinfo is None or end <= start or end - start > timedelta(days=7):
        raise HTTPException(422, "Timezone-aware range of at most 7 days required")
    async with pool.connection() as conn:
        if not await one(conn, "SELECT id FROM devices WHERE id=%s AND workspace_id=%s", (device_id, ws["id"])):
            raise HTTPException(404, "Device not found")
        return await many(
            conn,
            "SELECT event_id,recorded_at,speed,bearing,accuracy,battery_level,ST_X(coordinates::geometry) lng,ST_Y(coordinates::geometry) lat FROM location_events WHERE workspace_id=%s AND device_id=%s AND recorded_at>=%s AND recorded_at<=%s ORDER BY recorded_at,event_id LIMIT %s OFFSET %s",
            (ws["id"], device_id, start, end, limit, offset),
        )


@app.get("/api/v1/geofences")
async def fences(ws=Depends(workspace)):
    async with pool.connection() as conn:
        return await many(
            conn,
            "SELECT id,name,enabled,dwell_seconds,ST_AsGeoJSON(geometry)::json geometry FROM geofences WHERE workspace_id=%s ORDER BY name LIMIT 1000",
            (ws["id"],),
        )


@app.post("/api/v1/geofences", status_code=201)
async def create_fence(body: Fence, ws=Depends(require("dispatcher"))):
    fid = uuid4()
    async with pool.connection() as conn:
        if body.geometry is not None:
            geometry = await one(conn, "SELECT ST_SetSRID(ST_GeomFromGeoJSON(%s),4326) g", (json.dumps(body.geometry),))
        elif body.center is not None and body.radius_m is not None:
            lng, lat = body.center
            if not -180 <= lng <= 180 or not -90 <= lat <= 90:
                raise HTTPException(422, "Invalid center")
            geometry = await one(
                conn,
                "SELECT ST_Buffer(ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,%s)::geometry g",
                (lng, lat, body.radius_m),
            )
        else:
            raise HTTPException(422, "Provide polygon geometry or center and radius_m")
        valid = await one(
            conn,
            "SELECT ST_IsValid(%s::geometry) valid, ST_IsEmpty(%s::geometry) empty",
            (geometry["g"], geometry["g"]),
        )
        if not valid["valid"] or valid["empty"]:
            raise HTTPException(422, "Invalid polygon topology")
        await conn.execute(
            "INSERT INTO geofences(id,workspace_id,name,geometry,dwell_seconds) VALUES (%s,%s,%s,ST_Multi(%s::geometry),%s)",
            (fid, ws["id"], body.name, geometry["g"], body.dwell_seconds),
        )
        await audit(conn, ws, "geofence.created", fid)
    return {"id": fid, "name": body.name}


@app.get("/api/v1/geofence-events")
async def fence_events(ws=Depends(workspace), device_id: UUID | None = None):
    async with pool.connection() as conn:
        return await many(
            conn,
            "SELECT e.id,e.device_id,e.geofence_id,e.event_type,e.recorded_at,g.name geofence_name FROM geofence_events e JOIN geofences g ON g.id=e.geofence_id WHERE e.workspace_id=%s AND (%s::uuid IS NULL OR e.device_id=%s) ORDER BY e.recorded_at DESC LIMIT 500",
            (ws["id"], device_id, device_id),
        )


@app.post("/api/v1/routes/optimize")
async def optimization(body: Optimization, ws=Depends(require("dispatcher"))):
    return await asyncio.to_thread(optimize, body.stops, body.start, body.end)


@app.post("/api/v1/routes", status_code=201)
async def route(body: RouteCreate, ws=Depends(require("dispatcher"))):
    if not settings.routing_url:
        raise HTTPException(503, "Configure ROUTING_URL for a prepared self-hosted OSRM dataset")
    coordinates = ";".join(f"{lng},{lat}" for lng, lat in body.waypoints)
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.get(
                f"{settings.routing_url}/route/v1/driving/{coordinates}",
                params={"overview": "full", "geometries": "geojson"},
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != "Ok" or not data.get("routes"):
                raise HTTPException(422, "No road route found")
            result = data["routes"][0]
    except httpx.HTTPError:
        raise HTTPException(503, "Routing engine unavailable") from None
    rid = uuid4()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO routes(id,workspace_id,name,geometry,waypoints,distance_m,duration_s,provider) VALUES (%s,%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)::geography,%s,%s,%s,%s)",
            (
                rid,
                ws["id"],
                body.name,
                json.dumps(result["geometry"]),
                Jsonb(body.waypoints),
                result["distance"],
                result["duration"],
                "osrm",
            ),
        )
        await audit(conn, ws, "route.created", rid)
    return {"id": rid, **result}


@app.get("/api/v1/routes")
async def routes(ws=Depends(workspace)):
    async with pool.connection() as conn:
        return await many(
            conn,
            "SELECT id,name,distance_m,duration_s,provider,ST_AsGeoJSON(geometry::geometry)::json geometry FROM routes WHERE workspace_id=%s ORDER BY name LIMIT 500",
            (ws["id"],),
        )


@app.post("/api/v1/route-assignments", status_code=201)
async def assignment(body: Assignment, ws=Depends(require("dispatcher"))):
    aid = uuid4()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO route_assignments(id,workspace_id,device_id,route_id,deviation_m,deviation_seconds) VALUES (%s,%s,%s,%s,%s,%s)",
            (aid, ws["id"], body.device_id, body.route_id, body.deviation_m, body.deviation_seconds),
        )
        await audit(conn, ws, "route.assigned", aid)
    return {"id": aid}


@app.get("/api/v1/alerts")
async def alerts(ws=Depends(workspace), limit: int = Query(200, ge=1, le=1000)):
    async with pool.connection() as conn:
        return await many(
            conn,
            "SELECT a.*,d.name device_name FROM alerts a JOIN devices d ON d.id=a.device_id WHERE a.workspace_id=%s ORDER BY a.created_at DESC LIMIT %s",
            (ws["id"], limit),
        )


@app.patch("/api/v1/alerts/{alert_id}")
async def update_alert(alert_id: UUID, body: AlertUpdate, ws=Depends(require("operator"))):
    async with pool.connection() as conn:
        row = await one(
            conn,
            "UPDATE alerts SET state=%s,notes=%s,acknowledged_at=CASE WHEN %s='acknowledged' THEN now() ELSE acknowledged_at END,resolved_at=CASE WHEN %s='resolved' THEN now() ELSE resolved_at END WHERE id=%s AND workspace_id=%s RETURNING *",
            (body.state, body.notes, body.state, body.state, alert_id, ws["id"]),
        )
        if not row:
            raise HTTPException(404, "Alert not found")
        await audit(conn, ws, "alert." + body.state, alert_id)
        await emit(conn, ws["id"], "alert.updated", row)
    return row


@app.get("/api/v1/overview")
async def overview(ws=Depends(workspace)):
    async with pool.connection() as conn:
        fleet = await devices(ws=ws, limit=1000, offset=0, status=None, team_id=None)
        counts = {
            s: sum(d["state"] == s for d in fleet)
            for s in ("moving", "idle", "stopped", "offline", "unknown", "online")
        }
        totals = await one(
            conn,
            """SELECT (SELECT count(*) FROM trips WHERE workspace_id=%s AND ended_at IS NULL) active_trips,
               (SELECT coalesce(sum(distance_m),0) FROM historical_metrics
                WHERE workspace_id=%s AND date=(now() AT TIME ZONE 'UTC')::date) distance_today_m""",
            (ws["id"], ws["id"]),
        )
        alert_count = await one(
            conn, "SELECT count(*) open_alerts FROM alerts WHERE workspace_id=%s AND state<>'resolved'", (ws["id"],)
        )
    return {"devices": len(fleet), "states": counts, **totals, **alert_count, "fleet_limit": 1000}


@app.get("/api/v1/trips")
async def trips(ws=Depends(workspace)):
    async with pool.connection() as conn:
        return await many(
            conn, "SELECT * FROM trips WHERE workspace_id=%s ORDER BY started_at DESC LIMIT 500", (ws["id"],)
        )


@app.get("/api/v1/stops")
async def stops(ws=Depends(workspace), device_id: UUID | None = None):
    async with pool.connection() as conn:
        return await many(
            conn,
            "SELECT id,device_id,arrived_at,departed_at,ST_X(coordinates::geometry) lng,ST_Y(coordinates::geometry) lat FROM stops WHERE workspace_id=%s AND (%s::uuid IS NULL OR device_id=%s) ORDER BY arrived_at DESC LIMIT 500",
            (ws["id"], device_id, device_id),
        )


@app.get("/api/v1/analytics/heatmap")
async def heatmap(
    start: datetime,
    end: datetime,
    ws=Depends(workspace),
    device_id: UUID | None = None,
    grid_degrees: float = Query(0.001, ge=0.0001, le=1),
):
    if start.tzinfo is None or end.tzinfo is None or end <= start or end - start > timedelta(days=90):
        raise HTTPException(422, "Timezone-aware range of at most 90 days required")
    async with pool.connection() as conn:
        return await many(
            conn,
            """SELECT ST_X(g) lng,ST_Y(g) lat,count(*) weight FROM (
           SELECT ST_SnapToGrid(coordinates::geometry,%s) g FROM location_events
           WHERE workspace_id=%s AND recorded_at BETWEEN %s AND %s AND (%s::uuid IS NULL OR device_id=%s)
           ) points GROUP BY g ORDER BY weight DESC LIMIT 10000""",
            (grid_degrees, ws["id"], start, end, device_id, device_id),
        )


@app.get("/api/v1/reports/trips.csv")
async def trip_report(ws=Depends(workspace)):
    rows = await trips(ws)
    fields = ["id", "device_id", "started_at", "ended_at", "distance_m", "moving_seconds", "idle_seconds", "max_speed"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="geopulse-trips.csv"'},
    )


@app.post("/api/v1/api-keys", status_code=201)
async def create_key(body: KeyCreate, ws=Depends(require("admin"))):
    token, kid = opaque("gpk"), uuid4()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO api_keys(id,workspace_id,name,secret_hash,scopes,expires_at) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                kid,
                ws["id"],
                body.name,
                digest(token),
                body.scopes,
                datetime.now(timezone.utc) + timedelta(days=body.lifetime_days),
            ),
        )
        await audit(conn, ws, "api_key.created", kid)
    return {"id": kid, "secret": token}


@app.get("/api/v1/api-keys")
async def keys(ws=Depends(require("admin"))):
    async with pool.connection() as conn:
        return await many(
            conn,
            "SELECT id,name,scopes,expires_at,revoked_at,last_used_at FROM api_keys WHERE workspace_id=%s",
            (ws["id"],),
        )


@app.delete("/api/v1/api-keys/{key_id}", status_code=204)
async def revoke_key(key_id: UUID, ws=Depends(require("admin"))):
    async with pool.connection() as conn:
        row = await one(
            conn,
            "UPDATE api_keys SET revoked_at=now() WHERE id=%s AND workspace_id=%s RETURNING id",
            (key_id, ws["id"]),
        )
        if not row:
            raise HTTPException(404, "API key not found")
        await audit(conn, ws, "api_key.revoked", key_id)


@app.post("/api/v1/saved-views", status_code=201)
async def save_view(body: SavedView, ws=Depends(workspace)):
    if not ws["user_id"] or len(json.dumps(body.configuration)) > 16000:
        raise HTTPException(422, "User and bounded configuration required")
    vid = uuid4()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO saved_views VALUES (%s,%s,%s,%s,%s)",
            (vid, ws["id"], ws["user_id"], body.name, Jsonb(body.configuration)),
        )
    return {"id": vid}


@app.get("/api/v1/saved-views")
async def views(ws=Depends(workspace)):
    async with pool.connection() as conn:
        return await many(
            conn,
            "SELECT id,name,configuration FROM saved_views WHERE workspace_id=%s AND user_id=%s",
            (ws["id"], ws["user_id"]),
        )


@app.get("/api/v1/audit-log")
async def logs(ws=Depends(require("admin"))):
    async with pool.connection() as conn:
        return await many(
            conn, "SELECT * FROM audit_logs WHERE workspace_id=%s ORDER BY created_at DESC LIMIT 500", (ws["id"],)
        )


# Fixed table mapping: never interpolate caller-provided SQL identifiers.
for entity in ("teams", "drivers", "vehicles"):

    def make_list(table):
        async def listing(ws=Depends(workspace)):
            async with pool.connection() as conn:
                return await many(
                    conn,
                    sql.SQL("SELECT id,name FROM {} WHERE workspace_id=%s ORDER BY name LIMIT 1000").format(
                        sql.Identifier(table)
                    ),
                    (ws["id"],),
                )

        return listing

    def make_create(table):
        async def creation(body: Named, ws=Depends(require("dispatcher"))):
            rid = uuid4()
            async with pool.connection() as conn:
                await conn.execute(
                    sql.SQL("INSERT INTO {}(id,workspace_id,name) VALUES (%s,%s,%s)").format(sql.Identifier(table)),
                    (rid, ws["id"], body.name),
                )
                await audit(conn, ws, table + ".created", rid)
            return {"id": rid, "name": body.name}

        return creation

    app.add_api_route("/api/v1/" + entity, make_list(entity), methods=["GET"], name="list_" + entity)
    app.add_api_route(
        "/api/v1/" + entity, make_create(entity), methods=["POST"], status_code=201, name="create_" + entity
    )


@app.post("/api/v1/realtime/ticket")
async def ticket(ws=Depends(workspace)):
    if ws["api_key"]:
        raise HTTPException(403, "Realtime requires user session")
    value = opaque("gpw")
    await redis.set(
        "ticket:" + digest(value), json.dumps({"workspace_id": str(ws["id"]), "user_id": str(ws["user_id"])}), ex=30
    )
    return {"ticket": value, "expires_in": 30}


@app.websocket("/api/v1/realtime")
async def realtime(socket: WebSocket, ticket: str = "", device_id: UUID | None = None):
    if socket.headers.get("origin") not in settings.origins:
        await socket.close(code=4403)
        return
    raw = await redis.getdel("ticket:" + digest(ticket))
    if not raw:
        await socket.close(code=4401)
        return
    identity = json.loads(raw)
    async with pool.connection() as conn:
        member = await one(
            conn,
            "SELECT role FROM memberships WHERE workspace_id=%s AND user_id=%s",
            (identity["workspace_id"], identity["user_id"]),
        )
        target = not device_id or await one(
            conn, "SELECT id FROM devices WHERE id=%s AND workspace_id=%s", (device_id, identity["workspace_id"])
        )
    if not member or not target:
        await socket.close(code=4403)
        return
    await socket.accept()
    pubsub = redis.pubsub()
    await pubsub.subscribe("workspace:" + identity["workspace_id"])
    await redis.incr("ws:connections")
    await socket.send_json({"type": "connected", "resync_required": True})
    last_check = time.monotonic()
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
            if msg:
                payload = json.loads(msg["data"])
                if not device_id or payload.get("data", {}).get("device_id") == str(device_id):
                    await socket.send_json(payload)
            if time.monotonic() - last_check > 20:
                async with pool.connection() as conn:
                    still_member = await one(
                        conn,
                        "SELECT 1 FROM memberships WHERE workspace_id=%s AND user_id=%s",
                        (identity["workspace_id"], identity["user_id"]),
                    )
                if not still_member:
                    await socket.close(code=4403)
                    break
                await socket.send_json({"type": "heartbeat"})
                last_check = time.monotonic()
            # Receive disconnect/heartbeat without blocking publication.
            try:
                incoming = await asyncio.wait_for(socket.receive(), timeout=0.01)
                if incoming["type"] == "websocket.disconnect":
                    break
            except asyncio.TimeoutError:
                pass
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await pubsub.aclose()
        await redis.decr("ws:connections")


@app.get("/metrics", include_in_schema=False)
async def metrics():
    # Internal Docker network only; Caddy does not route this endpoint to the API.
    async with pool.connection() as conn:
        row = await one(
            conn,
            "SELECT count(*) pending,coalesce(extract(epoch from now()-min(created_at)),0) age FROM outbox WHERE published_at IS NULL",
        )
        repairs = await one(
            conn,
            "SELECT count(*) pending,coalesce(extract(epoch from now()-min(requested_at)),0) age FROM distance_reconciliation_jobs",
        )
    heartbeat = await redis.get("worker:heartbeat")
    worker_age = (
        (datetime.now(timezone.utc) - datetime.fromisoformat(str(heartbeat))).total_seconds() if heartbeat else -1
    )
    payload = f"geopulse_outbox_pending {row['pending']}\ngeopulse_outbox_oldest_age_seconds {row['age']}\ngeopulse_worker_heartbeat_age_seconds {worker_age}\ngeopulse_websocket_connections {int(await redis.get('ws:connections') or 0)}\n"
    payload += f"geopulse_distance_reconciliation_pending {repairs['pending']}\ngeopulse_distance_reconciliation_oldest_age_seconds {repairs['age']}\n"
    return Response(payload, media_type="text/plain; version=0.0.4")


@app.get("/api/v1/devices/{device_id}")
async def device_detail(device_id: UUID, ws=Depends(workspace)):
    async with pool.connection() as conn:
        d = await one(
            conn,
            """SELECT d.id,d.name,d.active,d.device_type,d.last_seen,d.firmware_version,
          t.name team_name,v.name vehicle_name,dr.name driver_name FROM devices d
          LEFT JOIN teams t ON t.id=d.team_id LEFT JOIN vehicles v ON v.id=d.vehicle_id
          LEFT JOIN drivers dr ON dr.id=d.driver_id WHERE d.id=%s AND d.workspace_id=%s""",
            (device_id, ws["id"]),
        )
        if not d:
            raise HTTPException(404, "Device not found")
        route = await one(
            conn,
            """SELECT a.id,a.state,a.eta_seconds,r.name,r.distance_m,r.duration_s,
          ST_AsGeoJSON(r.geometry::geometry)::json geometry FROM route_assignments a JOIN routes r ON r.id=a.route_id
          WHERE a.device_id=%s AND a.state IN ('assigned','active')""",
            (device_id,),
        )
        fences = await many(
            conn,
            """SELECT g.id,g.name,s.entered_at FROM geofence_state s JOIN geofences g ON g.id=s.geofence_id
          WHERE s.device_id=%s AND s.inside AND g.enabled""",
            (device_id,),
        )
        events = await many(
            conn,
            "SELECT id,event_type,recorded_at,geofence_id FROM geofence_events WHERE device_id=%s ORDER BY recorded_at DESC LIMIT 20",
            (device_id,),
        )
    return {"device": d, "route": route, "geofences": fences, "recent_geofence_events": events}


from .schemas import WorkspaceSettings, RoleUpdate  # noqa: E402


@app.patch("/api/v1/settings")
async def workspace_settings(body: WorkspaceSettings, ws=Depends(require("admin"))):
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE organizations SET retention_days=%s,offline_seconds=%s,moving_speed=%s,stop_seconds=%s WHERE id=%s",
            (body.retention_days, body.offline_seconds, body.moving_speed, body.stop_seconds, ws["id"]),
        )
        await audit(conn, ws, "configuration.updated", ws["id"])
    return body


@app.get("/api/v1/members")
async def members(ws=Depends(require("admin"))):
    async with pool.connection() as conn:
        return await many(
            conn,
            "SELECT u.id,u.name,u.email,m.role FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=%s ORDER BY u.name",
            (ws["id"],),
        )


@app.patch("/api/v1/members/{user_id}")
async def role_update(user_id: UUID, body: RoleUpdate, ws=Depends(require("owner"))):
    async with pool.connection() as conn:
        row = await one(
            conn,
            "UPDATE memberships SET role=%s WHERE workspace_id=%s AND user_id=%s AND role<>'owner' RETURNING user_id,role",
            (body.role, ws["id"], user_id),
        )
        if not row:
            raise HTTPException(404, "Non-owner membership not found")
        await audit(conn, ws, "membership.role_changed", user_id)
    return row


from .webhooks import router as webhook_router  # noqa: E402

app.include_router(webhook_router)
