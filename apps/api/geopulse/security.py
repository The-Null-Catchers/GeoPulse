import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import Depends, Header, HTTPException, Request
from .config import settings
from .db import pool, one, redis

passwords = PasswordHasher()
ROLES = {"owner": 5, "admin": 4, "dispatcher": 3, "operator": 2, "viewer": 1}


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def opaque(prefix="gp") -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def access_token(user_id):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(minutes=15),
            "iss": "geopulse",
            "aud": "geopulse-api",
            "type": "access",
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def decode_access(token: str):
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience="geopulse-api",
            issuer="geopulse",
            options={"require": ["sub", "exp", "iat", "type"]},
        )
        if claims["type"] != "access":
            raise ValueError()
        return UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(401, "Invalid or expired access token") from None


def verify_password(raw: str, hashed: str):
    try:
        return passwords.verify(hashed, raw)
    except (VerifyMismatchError, InvalidHashError):
        return False


async def rate_limit(key: str, limit: int, seconds: int = 60):
    script = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"
    n = await redis.eval(script, 1, f"rate:{key}", seconds)
    if n > limit:
        raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": str(seconds)})


async def user(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required")
    return decode_access(authorization[7:])


async def workspace(request: Request, x_workspace_id: UUID = Header(), authorization: str = Header(default="")):
    return await authorize_workspace(request, x_workspace_id, authorization)


async def read_workspace(request: Request, x_workspace_id: UUID = Header(), authorization: str = Header(default="")):
    """Read-only query endpoints may use POST for a complex geometry body."""
    return await authorize_workspace(request, x_workspace_id, authorization, read_only=True)


async def authorize_workspace(request, x_workspace_id, authorization, read_only=False):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required")
    token = authorization[7:]
    async with pool.connection() as conn:
        if token.startswith("gpk_"):
            key = await one(
                conn,
                "SELECT * FROM api_keys WHERE secret_hash=%s AND workspace_id=%s AND revoked_at IS NULL AND expires_at>now()",
                (digest(token), x_workspace_id),
            )
            scope = "read" if read_only or request.method in ("GET", "HEAD") else "write"
            if not key or scope not in key["scopes"]:
                raise HTTPException(403, "API key lacks required workspace scope")
            await conn.execute("UPDATE api_keys SET last_used_at=now() WHERE id=%s", (key["id"],))
            await rate_limit(f"key:{key['id']}", 300)
            return {"id": x_workspace_id, "user_id": None, "role": "dispatcher", "api_key": True}
        uid = decode_access(token)
        member = await one(
            conn, "SELECT role FROM memberships WHERE workspace_id=%s AND user_id=%s", (x_workspace_id, uid)
        )
        if not member:
            raise HTTPException(403, "Workspace access denied")
        await rate_limit(f"user:{uid}", 600)
        return {"id": x_workspace_id, "user_id": uid, "role": member["role"], "api_key": False}


def require(minimum: str):
    async def check(ws=Depends(workspace)):
        if ROLES[ws["role"]] < ROLES[minimum]:
            raise HTTPException(403, "Insufficient role")
        return ws

    return check


async def device(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer gpd_"):
        raise HTTPException(401, "Device token required")
    async with pool.connection() as conn:
        row = await one(
            conn,
            "SELECT d.*,o.retention_days FROM devices d JOIN organizations o ON o.id=d.workspace_id WHERE token_hash=%s AND active",
            (digest(authorization[7:]),),
        )
    if not row:
        raise HTTPException(401, "Invalid or inactive device")
    await rate_limit(f"device:{row['id']}", 120)
    return row
