"""Workspace webhook configuration, durable jobs and pinned public-IP HTTPS delivery."""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import re
import socket
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4
import aiohttp
from aiohttp.abc import AbstractResolver
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.types.json import Jsonb
from pydantic import Field
from .config import settings
from .db import pool, one, many
from .schemas import Input, Named
from .security import require, opaque

EVENT_TYPES = (
    "device.online",
    "device.offline",
    "geofence.enter",
    "geofence.exit",
    "geofence.dwell",
    "alert.created",
    "alert.updated",
    "trip.started",
    "trip.completed",
)
MAX_ATTEMPTS = 5
router = APIRouter(prefix="/api/v1", tags=["webhooks"])


class WebhookCreate(Named):
    url: str = Field(min_length=10, max_length=2048)
    event_types: list[
        Literal[
            "device.online",
            "device.offline",
            "geofence.enter",
            "geofence.exit",
            "geofence.dwell",
            "alert.created",
            "alert.updated",
            "trip.started",
            "trip.completed",
        ]
    ] = Field(min_length=1, max_length=10)


class WebhookUpdate(Input):
    enabled: bool


def cipher() -> Fernet:
    if not settings.webhook_encryption_key:
        raise HTTPException(503, "Configure WEBHOOK_ENCRYPTION_KEY before provisioning webhooks")
    try:
        return Fernet(settings.webhook_encryption_key.encode())
    except (ValueError, TypeError):
        raise HTTPException(503, "Invalid webhook encryption key configuration") from None


def public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped or ip.sixtofour or ip.teredo:
            return False
        if ip in ipaddress.ip_network("64:ff9b::/96") or ip in ipaddress.ip_network("64:ff9b:1::/48"):
            return False
    return True


def validate_url(value: str) -> str:
    if any(ord(c) <= 32 for c in value) or "\\" in value:
        raise HTTPException(422, "Invalid webhook URL")
    try:
        u = urlsplit(value)
        host = (u.hostname or "").lower()
        if u.scheme != "https" or u.port not in (None, 443) or u.username or u.password or u.fragment:
            raise ValueError()
        if not re.fullmatch(r"[a-z0-9.-]+", host) or host.endswith("."):
            raise ValueError()
        allowed = tuple(h.lower() for h in settings.webhook_allowed_hosts)
        if host not in allowed:
            raise HTTPException(422, "Webhook host is not in WEBHOOK_ALLOWED_HOSTS")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not public_ip(str(address)):
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "Webhook requires approved HTTPS host, public IP and port 443") from None
    return value


class PublicResolver(AbstractResolver):
    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        host = host.lower()
        if host not in settings.webhook_allowed_hosts:
            raise OSError("Destination host denied")
        answers = await asyncio.get_running_loop().getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM)
        if not answers or any(not public_ip(str(answer[4][0])) for answer in answers):
            raise OSError("Destination address denied")
        # Numeric results are handed directly to the connector; it never resolves the hostname a second time.
        unique = {(answer[0], answer[4][0]) for answer in answers}
        return [
            {
                "hostname": host,
                "host": address,
                "port": port,
                "family": fam,
                "proto": socket.IPPROTO_TCP,
                "flags": socket.AI_NUMERICHOST,
            }
            for fam, address in sorted(unique)
        ]

    async def close(self):
        pass


def make_connector():
    return aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False, limit=1, force_close=True)


def body_bytes(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")


def signature(secret: str, timestamp: str, delivery_id: str, body: bytes) -> str:
    signed = timestamp.encode() + b"." + delivery_id.encode() + b"." + body
    return "v1=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class SendResult:
    http_status: int | None
    error: str | None = None
    retry_after: int | None = None

    @property
    def success(self):
        return self.http_status is not None and 200 <= self.http_status < 300

    @property
    def retryable(self):
        return self.http_status is None or self.http_status in (408, 429) or self.http_status >= 500


async def send_webhook(url: str, secret: str, delivery_id: str, payload: dict) -> SendResult:
    try:
        validate_url(url)
        body = body_bytes(payload)
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "GeoPulse-Webhooks/0.1",
            "X-GeoPulse-Delivery": delivery_id,
            "X-GeoPulse-Timestamp": timestamp,
            "X-GeoPulse-Signature": signature(secret, timestamp, delivery_id, body),
        }
        async with aiohttp.ClientSession(
            connector=make_connector(),
            timeout=aiohttp.ClientTimeout(total=10),
            trust_env=False,
            cookie_jar=aiohttp.DummyCookieJar(),
            auto_decompress=False,
        ) as client:
            async with client.post(url, data=body, headers=headers, allow_redirects=False) as response:
                retry_after = response.headers.get("Retry-After", "")
                delay = min(3600, max(1, int(retry_after))) if retry_after.isdigit() else None
                return SendResult(response.status, retry_after=delay)
    except HTTPException:
        return SendResult(400, "destination_denied")
    except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
        # Do not persist exception strings: these can contain URLs, credentials or endpoint-controlled content.
        return SendResult(None, "transport_error")


async def webhook_audit(conn, ws, action, resource):
    await conn.execute(
        "INSERT INTO audit_logs(id,workspace_id,user_id,action,resource_id) VALUES (%s,%s,%s,%s,%s)",
        (uuid4(), ws["id"], ws["user_id"], action, resource),
    )


@router.post("/webhooks", status_code=201)
async def create_webhook(body: WebhookCreate, ws=Depends(require("admin"))):
    url = validate_url(body.url)
    encrypted = cipher()
    token, wid = opaque("gph"), uuid4()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO webhooks(id,workspace_id,name,url,event_types,encrypted_secret) VALUES (%s,%s,%s,%s,%s,%s)",
            (wid, ws["id"], body.name, url, sorted(set(body.event_types)), encrypted.encrypt(token.encode()).decode()),
        )
        await webhook_audit(conn, ws, "webhook.created", wid)
    return {"id": wid, "name": body.name, "url": url, "signing_secret": token}


@router.get("/webhooks")
async def list_webhooks(ws=Depends(require("admin"))):
    async with pool.connection() as conn:
        return await many(
            conn,
            "SELECT id,name,url,event_types,enabled,created_at FROM webhooks WHERE workspace_id=%s ORDER BY created_at DESC LIMIT 200",
            (ws["id"],),
        )


@router.patch("/webhooks/{webhook_id}")
async def update_webhook(webhook_id: UUID, body: WebhookUpdate, ws=Depends(require("admin"))):
    async with pool.connection() as conn:
        row = await one(
            conn,
            "UPDATE webhooks SET enabled=%s WHERE id=%s AND workspace_id=%s RETURNING id,enabled",
            (body.enabled, webhook_id, ws["id"]),
        )
        if not row:
            raise HTTPException(404, "Webhook not found")
        if not body.enabled:
            await conn.execute(
                "UPDATE webhook_deliveries SET state='cancelled',lease_token=NULL,leased_until=NULL WHERE webhook_id=%s AND state IN ('pending','retry','sending')",
                (webhook_id,),
            )
        await webhook_audit(conn, ws, "webhook.configuration_changed", webhook_id)
    return row


@router.post("/webhooks/{webhook_id}/rotate-secret")
async def rotate_secret(webhook_id: UUID, ws=Depends(require("admin"))):
    token = opaque("gph")
    encrypted = cipher().encrypt(token.encode()).decode()
    async with pool.connection() as conn:
        row = await one(
            conn,
            "UPDATE webhooks SET encrypted_secret=%s WHERE id=%s AND workspace_id=%s RETURNING id",
            (encrypted, webhook_id, ws["id"]),
        )
        if not row:
            raise HTTPException(404, "Webhook not found")
        await webhook_audit(conn, ws, "webhook.secret_rotated", webhook_id)
    return {"id": webhook_id, "signing_secret": token}


@router.get("/webhook-deliveries")
async def deliveries(ws=Depends(require("admin")), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    async with pool.connection() as conn:
        return await many(
            conn,
            """SELECT id,webhook_id,event_id,device_id,payload->>'type' event_type,state,attempts,
          next_attempt_at,last_http_status,last_error,created_at,delivered_at
          FROM webhook_deliveries WHERE workspace_id=%s ORDER BY created_at DESC,id LIMIT %s OFFSET %s""",
            (ws["id"], limit, offset),
        )


@router.get("/webhook-deliveries/{delivery_id}/attempts")
async def attempts(delivery_id: UUID, ws=Depends(require("admin"))):
    async with pool.connection() as conn:
        if not await one(
            conn, "SELECT id FROM webhook_deliveries WHERE id=%s AND workspace_id=%s", (delivery_id, ws["id"])
        ):
            raise HTTPException(404, "Delivery not found")
        return await many(
            conn,
            "SELECT attempt,started_at,finished_at,http_status,error,duration_ms FROM webhook_attempts WHERE delivery_id=%s ORDER BY attempt",
            (delivery_id,),
        )


@router.post("/webhook-deliveries/{delivery_id}/retry")
async def retry_delivery(delivery_id: UUID, ws=Depends(require("admin"))):
    async with pool.connection() as conn:
        row = await one(
            conn,
            """UPDATE webhook_deliveries d SET state='retry',next_attempt_at=now(),last_error=NULL
          FROM webhooks h WHERE d.id=%s AND d.workspace_id=%s AND h.id=d.webhook_id AND h.enabled
          AND d.state='failed' AND d.attempts<%s RETURNING d.id,d.state""",
            (delivery_id, ws["id"], MAX_ATTEMPTS),
        )
        if not row:
            raise HTTPException(409, "Delivery missing, disabled, exhausted or not failed")
        await webhook_audit(conn, ws, "webhook.delivery_retried", delivery_id)
    return row


async def enqueue(conn, workspace_id, outbox_id: int, payload: dict):
    if payload["type"] not in EVENT_TYPES:
        return
    hooks = await many(
        conn,
        "SELECT id FROM webhooks WHERE workspace_id=%s AND enabled AND %s=ANY(event_types)",
        (workspace_id, payload["type"]),
    )
    device_id = payload.get("data", {}).get("device_id")
    for hook in hooks:
        await conn.execute(
            "INSERT INTO webhook_deliveries(id,workspace_id,webhook_id,event_id,device_id,payload) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(webhook_id,event_id) DO NOTHING",
            (uuid4(), workspace_id, hook["id"], outbox_id, device_id, Jsonb(payload)),
        )


async def deliver_once() -> bool:
    async with pool.connection() as conn:
        await conn.execute(
            """UPDATE webhook_deliveries SET state='failed',lease_token=NULL,leased_until=NULL,last_error='attempts_exhausted'
          WHERE attempts>=%s AND (state IN ('pending','retry') OR (state='sending' AND leased_until<now()))""",
            (MAX_ATTEMPTS,),
        )
        claim = await one(
            conn,
            """SELECT d.*,h.url,h.encrypted_secret FROM webhook_deliveries d JOIN webhooks h ON h.id=d.webhook_id
          WHERE h.enabled AND d.attempts<%s AND d.next_attempt_at<=now()
          AND (d.state IN ('pending','retry') OR (d.state='sending' AND d.leased_until<now()))
          ORDER BY d.next_attempt_at,d.id LIMIT 1 FOR UPDATE OF d SKIP LOCKED""",
            (MAX_ATTEMPTS,),
        )
        if not claim:
            return False
        lease = uuid4()
        attempt = claim["attempts"] + 1
        await conn.execute(
            "UPDATE webhook_deliveries SET state='sending',attempts=%s,lease_token=%s,leased_until=now()+interval '45 seconds' WHERE id=%s",
            (attempt, lease, claim["id"]),
        )
        await conn.execute(
            "UPDATE webhook_attempts SET finished_at=now(),error='lease_expired_unknown_outcome' WHERE delivery_id=%s AND finished_at IS NULL",
            (claim["id"],),
        )
        await conn.execute("INSERT INTO webhook_attempts(delivery_id,attempt) VALUES (%s,%s)", (claim["id"], attempt))
    started = time.perf_counter()
    try:
        secret = cipher().decrypt(claim["encrypted_secret"].encode()).decode()
        result = await send_webhook(claim["url"], secret, str(claim["id"]), claim["payload"])
    except Exception:
        result = SendResult(400, "signing_configuration_error")
    elapsed = (time.perf_counter() - started) * 1000
    state = "delivered" if result.success else "retry" if result.retryable and attempt < MAX_ATTEMPTS else "failed"
    delay = result.retry_after or min(3600, 5 * 2 ** (attempt - 1))
    async with pool.connection() as conn:
        updated = await one(
            conn,
            """UPDATE webhook_deliveries SET state=%s,lease_token=NULL,leased_until=NULL,
          last_http_status=%s,last_error=%s,next_attempt_at=now()+make_interval(secs=>%s),
          delivered_at=CASE WHEN %s='delivered' THEN now() ELSE delivered_at END
          WHERE id=%s AND state='sending' AND lease_token=%s RETURNING id""",
            (state, result.http_status, result.error, delay, state, claim["id"], lease),
        )
        if updated:
            await conn.execute(
                "UPDATE webhook_attempts SET finished_at=now(),http_status=%s,error=%s,duration_ms=%s WHERE delivery_id=%s AND attempt=%s",
                (result.http_status, result.error, elapsed, claim["id"], attempt),
            )
    return True
