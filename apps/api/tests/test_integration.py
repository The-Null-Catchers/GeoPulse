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
