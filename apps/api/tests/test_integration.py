"""Uses real PostgreSQL/PostGIS and Redis. RUN_INTEGRATION=1 is required; no SQLite substitutes."""

import os
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Requires real PostGIS and Redis")


@pytest.fixture(scope="module")
def client():
    from geopulse.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def independent_registration_budget(client):
    # Each scenario has its own admission budget; dedicated regression below checks the actual limit.
    from geopulse.db import redis

    client.portal.call(redis.delete, "rate:register:testclient")


def account(client):
    uid = str(uuid4())[:8]
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": uid + "@example.test",
            "name": "Test operator",
            "organization": "Test fleet",
            "password": "test-only-passphrase-123",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return body, {"Authorization": "Bearer " + body["access_token"], "X-Workspace-ID": body["workspace_id"]}


def create_device(client, headers):
    r = client.post("/api/v1/devices", headers=headers, json={"name": "Tracker"})
    assert r.status_code == 201, r.text
    return r.json()


def gps(stamp=None, **override):
    return {
        "event_id": str(uuid4()),
        "recorded_at": (stamp or datetime.now(timezone.utc)).isoformat(),
        "lng": 34.46,
        "lat": 31.51,
        "speed": 5,
        "bearing": 30,
        "accuracy": 5,
        "battery_level": 90,
        **override,
    }


def drain(client):
    from worker.main import drain_once

    async def all_events():
        for _ in range(100):
            if not await drain_once():
                break

    client.portal.call(all_events)


def test_ingestion_isolation_idempotency_spatial_history(client):
    a, h = account(client)
    b, hb = account(client)
    dev = create_device(client, h)
    dh = {"Authorization": "Bearer " + dev["token"]}
    p = gps()
    assert client.post("/api/v1/locations", json=p).status_code == 401
    for inserted, duplicates in [(1, 0), (0, 1)]:
        r = client.post("/api/v1/locations", headers=dh, json=p)
        assert r.status_code == 202, r.text
        assert r.json()["inserted"] == inserted and r.json()["duplicates"] == duplicates
    old = gps(datetime.now(timezone.utc) - timedelta(hours=1), lng=34.40)
    assert client.post("/api/v1/locations", headers=dh, json=old).status_code == 202
    drain(client)
    rows = client.get("/api/v1/devices", headers=h).json()
    assert rows[0]["lng"] == pytest.approx(34.46)
    assert client.get("/api/v1/devices", headers=hb).json() == []
    assert client.get("/api/v1/devices/nearby?lat=31.51&lng=34.46&radius=100", headers=h).json()[0]["id"] == dev["id"]
    assert client.get("/api/v1/devices/nearby?lat=31.51&lng=34.46&radius=100", headers=hb).json() == []
    params = {
        "start": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "end": datetime.now(timezone.utc).isoformat(),
    }
    assert len(client.get("/api/v1/devices/" + dev["id"] + "/history", headers=h, params=params).json()) == 2
    assert client.get("/api/v1/devices/" + dev["id"] + "/history", headers=hb, params=params).status_code == 404
    assert client.patch("/api/v1/devices/" + dev["id"], headers=hb, json={"active": False}).status_code == 404
    assert client.patch("/api/v1/devices/" + dev["id"], headers=h, json={"active": False}).status_code == 200
    assert client.post("/api/v1/locations", headers=dh, json=gps()).status_code == 401


def test_geofence_enter_dwell_exit(client):
    a, h = account(client)
    dev = create_device(client, h)
    dh = {"Authorization": "Bearer " + dev["token"]}
    r = client.post(
        "/api/v1/geofences",
        headers=h,
        json={"name": "Depot", "center": [34.46, 31.51], "radius_m": 100, "dwell_seconds": 10},
    )
    assert r.status_code == 201, r.text
    now = datetime.now(timezone.utc) - timedelta(seconds=30)
    points = [gps(now, speed=0), gps(now + timedelta(seconds=15), speed=0), gps(now + timedelta(seconds=25), lng=34.47)]
    assert client.post("/api/v1/locations/batch", headers=dh, json={"points": points}).status_code == 202
    drain(client)
    events = client.get("/api/v1/geofence-events", headers=h).json()
    assert [e["event_type"] for e in events] == ["exit", "dwell", "enter"]


def test_refresh_reuse_revokes_rotated_family(client):
    a, h = account(client)
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": a["refresh_token"]})
    assert r.status_code == 200, r.text
    rotated = r.json()["refresh_token"]
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": a["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": rotated}).status_code == 401


def test_websocket_ticket_single_use_and_delivery(client):
    a, h = account(client)
    dev = create_device(client, h)
    ticket = client.post("/api/v1/realtime/ticket", headers=h).json()["ticket"]
    with client.websocket_connect(
        "/api/v1/realtime?ticket=" + ticket, headers={"Origin": "http://localhost:3000"}
    ) as ws:
        assert ws.receive_json()["type"] == "connected"
        p = gps()
        assert (
            client.post("/api/v1/locations", headers={"Authorization": "Bearer " + dev["token"]}, json=p).status_code
            == 202
        )
        drain(client)
        event = ws.receive_json()
        assert event["type"] == "location.updated" and event["data"]["device_id"] == dev["id"]
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/realtime?ticket=" + ticket, headers={"Origin": "http://localhost:3000"}):
            pass


def test_viewer_permissions_and_assignment_foreign_workspace(client):
    a, h = account(client)
    b, hb = account(client)
    # A cannot use B's team even with a legitimate dispatcher role in A.
    team = client.post("/api/v1/teams", headers=hb, json={"name": "Other workspace"}).json()
    assert (
        client.post(
            "/api/v1/devices", headers=h, json={"name": "Illegal assignment", "team_id": team["id"]}
        ).status_code
        == 404
    )
    from geopulse.db import pool

    async def downgrade():
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s",
                (a["workspace_id"], a["user_id"]),
            )

    client.portal.call(downgrade)
    assert client.post("/api/v1/devices", headers=h, json={"name": "Forbidden"}).status_code == 403


def test_trip_stop_and_route_deviation_eta(client):
    a, h = account(client)
    dev = create_device(client, h)
    dh = {"Authorization": "Bearer " + dev["token"]}
    assert (
        client.patch(
            "/api/v1/settings",
            headers=h,
            json={"retention_days": 90, "offline_seconds": 120, "moving_speed": 1.5, "stop_seconds": 30},
        ).status_code
        == 200
    )
    from geopulse.db import pool

    rid = str(uuid4())

    async def insert_route():
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO routes(id,workspace_id,name,geometry,waypoints,distance_m,duration_s,provider) VALUES (%s,%s,'Test route',ST_GeogFromText('SRID=4326;LINESTRING(34.46 31.50,34.46 31.55)'),'[]',5550,600,'test-fixture')",
                (rid, a["workspace_id"]),
            )

    client.portal.call(insert_route)
    assert (
        client.post(
            "/api/v1/route-assignments",
            headers=h,
            json={"device_id": dev["id"], "route_id": rid, "deviation_m": 100, "deviation_seconds": 10},
        ).status_code
        == 201
    )
    now = datetime.now(timezone.utc) - timedelta(seconds=75)
    points = [
        gps(now, lng=34.47, speed=8),
        gps(now + timedelta(seconds=15), lng=34.47, speed=8),
        gps(now + timedelta(seconds=20), lng=34.47, lat=31.511, speed=0),
        gps(now + timedelta(seconds=55), lng=34.47, lat=31.511, speed=0),
    ]
    assert client.post("/api/v1/locations/batch", headers=dh, json={"points": points}).status_code == 202
    drain(client)
    assert client.get("/api/v1/devices", headers=h).json()[0]["state"] == "stopped"
    trips = client.get("/api/v1/trips", headers=h).json()
    assert len(trips) == 1 and trips[0]["ended_at"] is not None and trips[0]["distance_m"] > 0
    assert len(client.get("/api/v1/stops", headers=h).json()) == 1
    alerts = client.get("/api/v1/alerts", headers=h).json()
    assert any(alert["kind"] == "route.deviation" for alert in alerts)
    detail = client.get("/api/v1/devices/" + dev["id"], headers=h).json()
    assert 0 < detail["route"]["eta_seconds"] < 600


def test_api_key_scopes_revocation_and_history_erasure(client):
    a, h = account(client)
    dev = create_device(client, h)
    created = client.post(
        "/api/v1/api-keys", headers=h, json={"name": "Read key", "scopes": ["read"], "lifetime_days": 1}
    )
    assert created.status_code == 201
    key = created.json()
    kh = {"Authorization": "Bearer " + key["secret"], "X-Workspace-ID": a["workspace_id"]}
    assert client.get("/api/v1/devices", headers=kh).status_code == 200
    assert client.post("/api/v1/devices", headers=kh, json={"name": "Forbidden"}).status_code == 403
    assert "secret_hash" not in client.get("/api/v1/api-keys", headers=h).text
    assert client.delete("/api/v1/api-keys/" + key["id"], headers=h).status_code == 204
    assert client.get("/api/v1/devices", headers=kh).status_code == 403
    assert (
        client.post("/api/v1/locations", headers={"Authorization": "Bearer " + dev["token"]}, json=gps()).status_code
        == 202
    )
    drain(client)
    assert client.delete("/api/v1/devices/" + dev["id"] + "/history", headers=h).status_code == 204
    drain(client)
    assert client.get("/api/v1/devices", headers=h).json()[0]["lng"] is None


def test_invalid_polygon_topology(client):
    a, h = account(client)
    geometry = {
        "type": "Polygon",
        "coordinates": [[[34.46, 31.5], [34.47, 31.51], [34.46, 31.51], [34.47, 31.5], [34.46, 31.5]]],
    }
    assert (
        client.post("/api/v1/geofences", headers=h, json={"name": "Invalid bow tie", "geometry": geometry}).status_code
        == 422
    )


def test_webhooks_durable_queue_retry_delivery_isolation_and_privacy(client, monkeypatch, tmp_path):
    from dataclasses import replace
    from cryptography.fernet import Fernet
    from aiohttp import web
    from geopulse import webhooks as hooks
    from geopulse.db import pool
    from test_webhooks import receiver

    monkeypatch.setattr(
        hooks,
        "settings",
        replace(
            hooks.settings,
            webhook_encryption_key=Fernet.generate_key().decode(),
            webhook_allowed_hosts=("receiver.test",),
        ),
    )
    a, h = account(client)
    b, hb = account(client)
    dev = create_device(client, h)
    created = client.post(
        "/api/v1/webhooks",
        headers=h,
        json={"name": "Alert receiver", "url": "https://receiver.test/hook", "event_types": ["alert.created"]},
    )
    assert created.status_code == 201, created.text
    hook = created.json()
    assert hook["signing_secret"] not in client.get("/api/v1/webhooks", headers=h).text
    assert client.get("/api/v1/webhooks", headers=hb).json() == []
    assert client.patch("/api/v1/webhooks/" + hook["id"], headers=hb, json={"enabled": False}).status_code == 404
    assert (
        client.post(
            "/api/v1/locations", headers={"Authorization": "Bearer " + dev["token"]}, json=gps(speed=35)
        ).status_code
        == 202
    )
    drain(client)
    deliveries = client.get("/api/v1/webhook-deliveries", headers=h).json()
    assert len(deliveries) == 1 and deliveries[0]["state"] == "pending"
    delivery = deliveries[0]
    assert client.get("/api/v1/webhook-deliveries/" + delivery["id"] + "/attempts", headers=hb).status_code == 404

    async def network_delivery():
        import hashlib
        import hmac

        seen = []

        async def handle(request):
            body = await request.read()
            signed = (
                request.headers["X-GeoPulse-Timestamp"].encode()
                + b"."
                + request.headers["X-GeoPulse-Delivery"].encode()
                + b"."
                + body
            )
            assert hmac.compare_digest(
                request.headers["X-GeoPulse-Signature"],
                "v1=" + hmac.new(hook["signing_secret"].encode(), signed, hashlib.sha256).hexdigest(),
            )
            seen.append(request.headers["X-GeoPulse-Delivery"])
            return web.Response(status=503 if len(seen) == 1 else 204)

        runner = await receiver(monkeypatch, tmp_path, handle)
        try:
            assert await hooks.deliver_once()
            async with pool.connection() as conn:
                row = await (
                    await conn.execute(
                        "SELECT state,attempts,last_http_status FROM webhook_deliveries WHERE id=%s", (delivery["id"],)
                    )
                ).fetchone()
                assert row["state"] == "retry" and row["attempts"] == 1 and row["last_http_status"] == 503
                await conn.execute("UPDATE webhook_deliveries SET next_attempt_at=now() WHERE id=%s", (delivery["id"],))
            assert await hooks.deliver_once()
            assert seen == [delivery["id"], delivery["id"]]
        finally:
            await runner.cleanup()

    client.portal.call(network_delivery)
    report = client.get("/api/v1/webhook-deliveries", headers=h).json()[0]
    assert report["state"] == "delivered" and report["attempts"] == 2
    attempts = client.get("/api/v1/webhook-deliveries/" + delivery["id"] + "/attempts", headers=h).json()
    assert [a["http_status"] for a in attempts] == [503, 204]
    rotated = client.post("/api/v1/webhooks/" + hook["id"] + "/rotate-secret", headers=h)
    assert rotated.status_code == 200 and rotated.json()["signing_secret"] != hook["signing_secret"]
    assert client.delete("/api/v1/devices/" + dev["id"] + "/history", headers=h).status_code == 204
    assert client.get("/api/v1/webhook-deliveries", headers=h).json() == []


def test_registration_rate_limit_is_enforced(client):
    for _ in range(10):
        account(client)
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": str(uuid4()) + "@example.test",
            "name": "Rate test",
            "organization": "Rate test",
            "password": "test-only-passphrase-123",
        },
    )
    assert r.status_code == 429 and r.headers["Retry-After"] == "3600"


def spatial_polygon():
    return {"type": "Polygon", "coordinates": [
        [[34.45, 31.50], [34.49, 31.50], [34.49, 31.54], [34.45, 31.54], [34.45, 31.50]],
        [[34.47, 31.52], [34.48, 31.52], [34.48, 31.53], [34.47, 31.53], [34.47, 31.52]],
    ]}


def test_spatial_polygon_boundary_hole_pagination_and_read_key(client):
    a, h = account(client)
    _, hb = account(client)
    expected = []
    for name, lng, lat in [("Inside", 34.46, 31.51), ("Boundary", 34.45, 31.51),
                           ("Hole", 34.475, 31.525), ("Outside", 34.50, 31.51),
                           ("Inactive", 34.46, 31.51), ("Foreign", 34.46, 31.51)]:
        headers = hb if name == "Foreign" else h
        dev = client.post("/api/v1/devices", headers=headers, json={"name": name}).json()
        assert client.post("/api/v1/locations", headers={"Authorization": "Bearer " + dev["token"]},
                           json=gps(lng=lng, lat=lat)).status_code == 202
        if name == "Inactive":
            assert client.patch("/api/v1/devices/" + dev["id"], headers=h, json={"active": False}).status_code == 200
        if name in ("Inside", "Boundary"):
            expected.append(dev["id"])
    drain(client)
    key = client.post("/api/v1/api-keys", headers=h,
                      json={"name": "Spatial reader", "scopes": ["read"], "lifetime_days": 1}).json()
    kh = {"Authorization": "Bearer " + key["secret"], "X-Workspace-ID": a["workspace_id"]}
    url = "/api/v1/spatial/devices/in-polygon"
    response = client.post(url + "?limit=1", headers=kh, json={"geometry": spatial_polygon()})
    assert response.status_code == 200, response.text
    first = response.json()
    second = client.post(url + "?limit=1&offset=1", headers=kh, json={"geometry": spatial_polygon()}).json()
    assert first["has_more"] and not second["has_more"]
    assert [first["items"][0]["id"], second["items"][0]["id"]] == sorted(expected)
    assert client.post("/api/v1/devices", headers=kh, json={"name": "Forbidden"}).status_code == 403
    assert client.post(url, headers={"Authorization": "Bearer " + key["secret"],
                                    "X-Workspace-ID": hb["X-Workspace-ID"]},
                       json={"geometry": spatial_polygon()}).status_code == 403
    # The geometry query is available to viewer users as well as read-only keys.
    from geopulse.db import pool

    async def downgrade():
        async with pool.connection() as conn:
            await conn.execute("UPDATE memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s",
                               (a["workspace_id"], a["user_id"]))
    client.portal.call(downgrade)
    assert client.post(url, headers=h, json={"geometry": spatial_polygon()}).status_code == 200
    invalid = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
    assert client.post(url, headers=h, json={"geometry": invalid}).status_code == 422


def test_spatial_closest_is_bounded_active_and_tenant_scoped(client):
    _, h = account(client)
    _, hb = account(client)
    own = create_device(client, h)
    foreign = create_device(client, hb)
    for dev, lng in [(own, 34.461), (foreign, 34.46)]:
        assert client.post("/api/v1/locations", headers={"Authorization": "Bearer " + dev["token"]},
                           json=gps(lng=lng)).status_code == 202
    drain(client)
    url = "/api/v1/spatial/devices/closest?lat=31.51&lng=34.46"
    response = client.get(url + "&radius=1000", headers=h)
    assert response.status_code == 200, response.text
    assert response.json()["id"] == own["id"]
    assert 90 < response.json()["distance_m"] < 100  # 0.001 longitude at this latitude, meters.
    assert client.get(url + "&radius=10", headers=h).json() is None
    assert client.patch("/api/v1/devices/" + own["id"], headers=h, json={"active": False}).status_code == 200
    assert client.get(url + "&radius=1000", headers=h).json() is None
    for params in ["lat=nan&lng=0", "lat=0&lng=inf", "lat=91&lng=0", "lat=0&lng=0&radius=0"]:
        assert client.get("/api/v1/spatial/devices/closest?" + params, headers=h).status_code == 422


def test_spatial_geofence_containment_respects_holes_boundaries_and_enabled(client):
    _, h = account(client)
    _, hb = account(client)
    body = {"name": "Operating area", "geometry": spatial_polygon()}
    own = client.post("/api/v1/geofences", headers=h, json=body).json()
    assert client.post("/api/v1/geofences", headers=hb, json=body).status_code == 201
    url = "/api/v1/spatial/geofences/containing"
    for lng, lat in [(34.46, 31.51), (34.45, 31.51)]:
        response = client.get(url, headers=h, params={"lng": lng, "lat": lat})
        assert response.status_code == 200, response.text
        assert [r["id"] for r in response.json()["items"]] == [own["id"]]
    assert client.get(url, headers=h, params={"lng": 34.475, "lat": 31.525}).json()["items"] == []
    from geopulse.db import pool

    async def disable():
        async with pool.connection() as conn:
            await conn.execute("UPDATE geofences SET enabled=false WHERE id=%s", (own["id"],))
    client.portal.call(disable)
    assert client.get(url, headers=h, params={"lng": 34.46, "lat": 31.51}).json()["items"] == []


def test_spatial_route_and_stop_search_isolation_and_time_window(client):
    a, h = account(client)
    b, hb = account(client)
    own, foreign = create_device(client, h), create_device(client, hb)
    for dev in (own, foreign):
        assert client.post("/api/v1/locations", headers={"Authorization": "Bearer " + dev["token"]},
                           json=gps()).status_code == 202
    drain(client)
    from geopulse.db import pool

    route_id, foreign_route = str(uuid4()), str(uuid4())
    stamp = datetime.now(timezone.utc) - timedelta(minutes=5)
    stop_id = str(uuid4())

    async def fixtures():
        async with pool.connection() as conn:
            for wid, rid in [(a["workspace_id"], route_id), (b["workspace_id"], foreign_route)]:
                await conn.execute("""INSERT INTO routes(id,workspace_id,name,geometry,waypoints,distance_m,duration_s,provider)
                    VALUES (%s,%s,'Spatial test route',ST_GeogFromText('SRID=4326;LINESTRING(34.46 31.50,34.46 31.55)'),
                    '[]',5550,600,'test-fixture')""", (rid, wid))
            for sid, wid, did, arrived, lng in [
                (stop_id, a["workspace_id"], own["id"], stamp, 34.46),
                (uuid4(), b["workspace_id"], foreign["id"], stamp, 34.46),
                (uuid4(), a["workspace_id"], own["id"], stamp - timedelta(days=3), 34.46),
                (uuid4(), a["workspace_id"], own["id"], stamp, 35.0),
            ]:
                await conn.execute("""INSERT INTO stops(id,workspace_id,device_id,arrived_at,departed_at,coordinates)
                    VALUES (%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,31.51),4326)::geography)""",
                    (sid, wid, did, arrived, arrived + timedelta(seconds=60), lng))
    client.portal.call(fixtures)
    url = "/api/v1/spatial/devices/near-route"
    result = client.get(url, headers=h, params={"route_id": route_id, "radius": 10})
    assert result.status_code == 200, result.text
    assert [r["id"] for r in result.json()["items"]] == [own["id"]]
    assert result.json()["items"][0]["distance_m"] < 0.1
    assert client.get(url, headers=h, params={"route_id": foreign_route}).status_code == 404
    assert client.get(url, headers=hb, params={"route_id": route_id}).status_code == 404
    params = {"lat": 31.51, "lng": 34.46, "radius": 100,
              "start": (stamp - timedelta(hours=1)).isoformat(), "end": (stamp + timedelta(hours=1)).isoformat()}
    url = "/api/v1/spatial/stops/nearby"
    result = client.get(url, headers=h, params=params)
    assert result.status_code == 200, result.text
    assert [r["id"] for r in result.json()["items"]] == [stop_id]
    for start, end in [("2026-01-01", "2026-01-02"), (params["end"], params["start"]),
                       ((stamp - timedelta(days=32)).isoformat(), params["end"])]:
        assert client.get(url, headers=h, params={**params, "start": start, "end": end}).status_code == 422


def test_replay_point_cursor_ties_large_history_and_workspace_isolation(client):
    a, h = account(client)
    _, foreign_headers = account(client)
    dev = create_device(client, h)
    stamp = datetime.now(timezone.utc) - timedelta(hours=2)
    points = [gps(stamp, event_id=str(uuid4()), lng=34.46 + n * .00001) for n in range(5)]
    assert client.post("/api/v1/locations/batch", headers={"Authorization": "Bearer " + dev["token"]},
                       json={"points": points}).status_code == 202
    url = "/api/v1/devices/" + dev["id"] + "/replay/points"
    params = {"start": (stamp - timedelta(minutes=1)).isoformat(), "end": (stamp + timedelta(hours=1)).isoformat(),
              "limit": 2}
    first = client.get(url, headers=h, params=params)
    assert first.status_code == 200, first.text
    rows, cursor = first.json()["items"], first.json()["next_cursor"]
    while cursor:
        result = client.get(url, headers=h, params={**params, "after_time": cursor["recorded_at"], "after_id": cursor["id"]})
        assert result.status_code == 200, result.text
        rows.extend(result.json()["items"])
        cursor = result.json()["next_cursor"]
    assert [r["event_id"] for r in rows] == sorted(p["event_id"] for p in points)
    assert client.get(url, headers=foreign_headers, params=params).status_code == 404
    assert client.get(url, headers=h, params={**params, "after_id": str(uuid4())}).status_code == 422
    assert client.get(url, headers=h, params={**params, "after_time": "2026-01-01", "after_id": str(uuid4())}).status_code == 422
    assert client.get(url, headers=h, params={**params, "start": params["end"]}).status_code == 422
    # Large persisted fixture validates pagination beyond the former first-5,000-point limit.
    from geopulse.db import pool

    async def history_fixture():
        async with pool.connection() as conn:
            await conn.execute("""INSERT INTO location_events(id,workspace_id,device_id,event_id,recorded_at,
                coordinates,speed,bearing,accuracy,source)
                SELECT gen_random_uuid(),%s,%s,gen_random_uuid(),%s::timestamptz+n*interval '0.1 second',
                ST_GeogFromText('SRID=4326;POINT(34.46 31.51)'),5,30,5,'gps' FROM generate_series(1,5101) n""",
                (a["workspace_id"], dev["id"], stamp))
    client.portal.call(history_fixture)
    large = client.get(url, headers=h, params={**params, "limit": 5000}).json()
    assert len(large["items"]) == 5000 and large["next_cursor"]
    tail = client.get(url, headers=h, params={**params, "limit": 5000,
                      "after_time": large["next_cursor"]["recorded_at"], "after_id": large["next_cursor"]["id"]}).json()
    assert len(tail["items"]) == 106 and tail["next_cursor"] is None
    assert len({p["event_id"] for p in large["items"] + tail["items"]}) == 5106


def test_replay_events_are_persisted_paged_and_history_erasure_applies(client):
    a, h = account(client)
    _, foreign_headers = account(client)
    dev = create_device(client, h)
    fence = client.post("/api/v1/geofences", headers=h,
                        json={"name": "Timeline depot", "center": [34.46, 31.51], "radius_m": 100}).json()
    stamp = datetime.now(timezone.utc) - timedelta(minutes=10)
    assert client.post("/api/v1/locations", headers={"Authorization": "Bearer " + dev["token"]},
                       json=gps(stamp)).status_code == 202
    # Persisted operational fixtures have coincident timestamps to exercise event cursor ties.
    from geopulse.db import pool

    async def events_fixture():
        async with pool.connection() as conn:
            await conn.execute("""INSERT INTO stops(id,workspace_id,device_id,arrived_at,departed_at,coordinates)
                VALUES (%s,%s,%s,%s,%s,ST_GeogFromText('SRID=4326;POINT(34.46 31.51)'))""",
                (uuid4(), a["workspace_id"], dev["id"], stamp, stamp + timedelta(seconds=120)))
            await conn.execute("""INSERT INTO geofence_events(id,workspace_id,device_id,geofence_id,event_type,
                recorded_at,coordinates) VALUES (%s,%s,%s,%s,'enter',%s,ST_GeogFromText('SRID=4326;POINT(34.46 31.51)'))""",
                (uuid4(), a["workspace_id"], dev["id"], fence["id"], stamp))
            for when, kind in [(stamp - timedelta(seconds=60), 'device.offline'), (stamp, 'battery.low')]:
                await conn.execute("""INSERT INTO alerts(id,workspace_id,device_id,kind,severity,recorded_at)
                    VALUES (%s,%s,%s,%s,'warning',%s)""", (uuid4(), a["workspace_id"], dev["id"], kind, when))
    client.portal.call(events_fixture)
    url = "/api/v1/devices/" + dev["id"] + "/replay/events"
    params = {"start": (stamp - timedelta(minutes=2)).isoformat(), "end": (stamp + timedelta(minutes=3)).isoformat(),
              "limit": 1}
    rows, cursor = [], None
    for _ in range(10):
        cursor_params = {"after_time": cursor["recorded_at"], "after_id": cursor["id"]} if cursor else {}
        response = client.get(url, headers=h, params={**params, **cursor_params})
        assert response.status_code == 200, response.text
        rows.extend(response.json()["items"])
        cursor = response.json()["next_cursor"]
        if not cursor:
            break
    assert len(rows) == 5 and len({e["id"] for e in rows}) == 5
    assert rows == sorted(rows, key=lambda r: (r["recorded_at"], r["id"]))
    assert {e["kind"] for e in rows} == {"stop.arrival", "stop.departure", "geofence.enter", "alert.created"}
    assert next(e for e in rows if e["kind"] == "stop.departure")["duration_seconds"] == 120
    assert next(e for e in rows if e["kind"] == "geofence.enter")["label"] == "Timeline depot"
    assert rows[0]["kind"] == "alert.created" and rows[0]["lng"] is None  # No invented GPS before the first point.
    assert next(e for e in rows if e["label"] == "battery.low")["lng"] == pytest.approx(34.46)
    assert client.get(url, headers=foreign_headers, params=params).status_code == 404
    assert client.get(url, headers=h, params={**params, "after_id": rows[0]["id"]}).status_code == 422
    assert client.delete("/api/v1/devices/" + dev["id"] + "/history", headers=h).status_code == 204
    assert client.get(url, headers=h, params=params).json()["items"] == []


def test_retention_expires_unlinked_geofence_events_per_workspace(client):
    a, h = account(client)
    b, hb = account(client)
    own, foreign = create_device(client, h), create_device(client, hb)
    fence_a = client.post("/api/v1/geofences", headers=h,
                          json={"name": "Retention fence", "center": [34.46, 31.51], "radius_m": 100}).json()
    fence_b = client.post("/api/v1/geofences", headers=hb,
                          json={"name": "Other fence", "center": [34.46, 31.51], "radius_m": 100}).json()
    assert client.patch("/api/v1/settings", headers=h,
                        json={"retention_days": 1, "offline_seconds": 120, "moving_speed": 1.5,
                              "stop_seconds": 30}).status_code == 200
    from geopulse.db import pool
    from worker.main import maintenance

    async def fixtures_and_retention():
        async with pool.connection() as conn:
            for wid, did, fid, age in [(a["workspace_id"], own["id"], fence_a["id"], 48),
                                      (a["workspace_id"], own["id"], fence_a["id"], 1),
                                      (b["workspace_id"], foreign["id"], fence_b["id"], 48)]:
                await conn.execute("""INSERT INTO geofence_events(id,workspace_id,device_id,geofence_id,
                    event_type,recorded_at,coordinates) VALUES (%s,%s,%s,%s,'enter',now()-make_interval(hours=>%s),
                    ST_GeogFromText('SRID=4326;POINT(34.46 31.51)'))""", (uuid4(), wid, did, fid, age))
        await maintenance()
    client.portal.call(fixtures_and_retention)
    events = client.get("/api/v1/geofence-events", headers=h).json()
    assert len(events) == 1
    assert datetime.fromisoformat(events[0]["recorded_at"]) > datetime.now(timezone.utc) - timedelta(days=1)
    assert len(client.get("/api/v1/geofence-events", headers=hb).json()) == 1
def repair_distances(client):
    from worker.reconciliation import reconcile_once

    async def all_jobs():
        for _ in range(100):
            if not await reconcile_once():
                return
        raise AssertionError("Reconciliation queue did not drain")

    client.portal.call(all_jobs)
    drain(client)


def test_late_distance_repairs_metrics_without_rewinding_or_duplicate_counting(client):
    _, h = account(client)
    dev = create_device(client, h)
    dh = {"Authorization": "Bearer " + dev["token"]}
    t = (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    day = t.date().isoformat()
    base = "/api/v1/analytics/distance"
    params = {"start": day, "end": day, "device_id": dev["id"]}
    for stamp in (t, t + timedelta(seconds=40)):
        assert client.post("/api/v1/locations", headers=dh, json=gps(stamp)).status_code == 202
    drain(client)
    assert client.get(base, headers=h, params=params).json()[0]["distance_m"] == 0
    late = gps(t + timedelta(seconds=20), lat=31.511)
    assert client.post("/api/v1/locations", headers=dh, json=late).json()["inserted"] == 1
    drain(client)
    assert client.get(base, headers=h, params=params).json()[0]["pending_devices"] == 1
    repair_distances(client)
    repaired = client.get(base, headers=h, params=params).json()[0]
    assert 220 < repaired["distance_m"] < 225
    assert repaired["pending_devices"] == 0
    snapshot = client.get("/api/v1/devices", headers=h).json()[0]
    assert snapshot["lat"] == 31.51
    assert datetime.fromisoformat(snapshot["recorded_at"]) == t + timedelta(seconds=40)
    assert snapshot["distance_today_m"] == 0  # Yesterday's total is not today's total.
    assert client.post("/api/v1/locations", headers=dh, json=late).json()["duplicates"] == 1
    drain(client)
    repair_distances(client)
    assert client.get(base, headers=h, params=params).json()[0] == repaired
    assert client.post("/api/v1/locations", headers=dh, json=gps(t + timedelta(seconds=60), lat=31.512)).status_code == 202
    drain(client)
    assert 440 < client.get(base, headers=h, params=params).json()[0]["distance_m"] < 450
    # An explicit repeat rebuild replaces the total, rather than adding the same segments again.
    assert client.post(base + "/recalculate", headers=h, params=params).status_code == 202
    repair_distances(client)
    assert 440 < client.get(base, headers=h, params=params).json()[0]["distance_m"] < 450


def test_distance_repair_crosses_utc_midnight_and_excludes_gaps_and_jumps(client):
    _, h = account(client)
    dev = create_device(client, h)
    dh = {"Authorization": "Bearer " + dev["token"]}
    t = (datetime.now(timezone.utc) - timedelta(days=2)).replace(hour=23, minute=59, second=40, microsecond=0)
    for stamp in (t, t + timedelta(seconds=40)):
        client.post("/api/v1/locations", headers=dh, json=gps(stamp))
    drain(client)
    client.post("/api/v1/locations", headers=dh, json=gps(t + timedelta(seconds=10), lat=31.511))
    drain(client)
    repair_distances(client)
    params = {"start": t.date().isoformat(), "end": (t + timedelta(days=1)).date().isoformat(), "device_id": dev["id"]}
    rows = client.get("/api/v1/analytics/distance", headers=h, params=params).json()
    assert len(rows) == 2 and all(110 < row["distance_m"] < 113 for row in rows)
    # A point one hour later starts a disconnected segment; an immediate continental jump is rejected.
    client.post("/api/v1/locations", headers=dh, json=gps(t + timedelta(hours=1), lat=31.52))
    client.post("/api/v1/locations", headers=dh, json=gps(t + timedelta(hours=1, seconds=1), lat=51.51))
    drain(client)
    client.post("/api/v1/locations", headers=dh, json=gps(t + timedelta(hours=1, seconds=1), lat=51.51,
                    event_id="ffffffff-ffff-ffff-ffff-ffffffffffff"))
    drain(client)
    repair_distances(client)
    final = client.get("/api/v1/analytics/distance", headers=h, params=params).json()
    assert [row["distance_m"] for row in final] == pytest.approx([row["distance_m"] for row in rows])


def test_distance_jobs_wait_for_pending_locations_and_erase_with_history(client):
    _, h = account(client)
    dev = create_device(client, h)
    dh = {"Authorization": "Bearer " + dev["token"]}
    t = datetime.now(timezone.utc) - timedelta(minutes=5)
    client.post("/api/v1/locations", headers=dh, json=gps(t))
    drain(client)
    client.post("/api/v1/locations", headers=dh, json=gps(t - timedelta(seconds=10), lat=31.511))
    drain(client)
    client.post("/api/v1/locations", headers=dh, json=gps(t + timedelta(seconds=10)))
    from worker.reconciliation import reconcile_once
    assert client.portal.call(reconcile_once) is False
    assert client.delete("/api/v1/devices/" + dev["id"] + "/history", headers=h).status_code == 204
    drain(client)
    repair_distances(client)
    params = {"start": t.date().isoformat(), "end": (t + timedelta(days=1)).date().isoformat(), "device_id": dev["id"]}
    assert all(row["distance_m"] == row["pending_devices"] == 0
               for row in client.get("/api/v1/analytics/distance", headers=h, params=params).json())


def test_daily_distance_api_is_scoped_bounded_and_available_to_read_keys(client):
    _, h = account(client)
    _, foreign_headers = account(client)
    dev = create_device(client, h)
    foreign = create_device(client, foreign_headers)
    day = datetime.now(timezone.utc).date()
    params = {"start": day.isoformat(), "end": day.isoformat(), "device_id": dev["id"]}
    url = "/api/v1/analytics/distance"
    assert client.get(url, headers=foreign_headers, params=params).status_code == 404
    assert client.get(url, headers=h, params={**params, "device_id": foreign["id"]}).status_code == 404
    assert client.get(url, params=params).status_code == 401
    assert client.get(url, headers=h, params={**params, "end": (day - timedelta(days=1)).isoformat()}).status_code == 422
    assert client.get(url, headers=h, params={**params, "end": (day + timedelta(days=90)).isoformat()}).status_code == 422
    key = client.post("/api/v1/api-keys", headers=h, json={"name": "Distance reader", "scopes": ["read"]}).json()
    read_headers = {"Authorization": "Bearer " + key["secret"], "X-Workspace-ID": h["X-Workspace-ID"]}
    assert client.get(url, headers=read_headers, params=params).status_code == 200
    assert client.post(url + "/recalculate", headers=read_headers, params=params).status_code == 403
    assert client.post(url + "/recalculate", headers=foreign_headers, params=params).status_code == 404
    assert client.post(url + "/recalculate", headers=h,
                      params={**params, "end": (day + timedelta(days=1)).isoformat()}).status_code == 422
    assert client.post(url + "/recalculate", headers=h,
                      params={**params, "start": (day - timedelta(days=91)).isoformat()}).status_code == 422
def test_distance_reconciliation_rollback_preserves_job_for_retry(client, monkeypatch):
    _, h = account(client)
    dev = create_device(client, h)
    dh = {"Authorization": "Bearer " + dev["token"]}
    t = datetime.now(timezone.utc) - timedelta(minutes=5)
    client.post("/api/v1/locations", headers=dh, json=gps(t))
    drain(client)
    client.post("/api/v1/locations", headers=dh, json=gps(t - timedelta(seconds=10), lat=31.511))
    drain(client)
    from worker import reconciliation
    original = reconciliation.emit

    async def fail_emit(*args, **kwargs):
        raise RuntimeError("Simulated transactional publication failure")

    monkeypatch.setattr(reconciliation, "emit", fail_emit)
    with pytest.raises(RuntimeError, match="Simulated transactional"):
        client.portal.call(reconciliation.reconcile_once)
    params = {"start": (t - timedelta(seconds=10)).date().isoformat(), "end": t.date().isoformat(), "device_id": dev["id"]}
    rows = client.get("/api/v1/analytics/distance", headers=h, params=params).json()
    assert sum(row["pending_devices"] for row in rows) >= 1
    assert sum(row["distance_m"] for row in rows) == 0
    monkeypatch.setattr(reconciliation, "emit", original)
    repair_distances(client)
    rows = client.get("/api/v1/analytics/distance", headers=h, params=params).json()
    assert 110 < sum(row["distance_m"] for row in rows) < 113
    assert sum(row["pending_devices"] for row in rows) == 0
