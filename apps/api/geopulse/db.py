from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis
from .config import settings

pool = AsyncConnectionPool(
    settings.database_url,
    open=False,
    min_size=2,
    max_size=20,
    kwargs={"row_factory": dict_row, "options": "-c timezone=UTC"},
)
redis = Redis.from_url(settings.redis_url, decode_responses=True)


async def one(conn, sql, args=()):
    return await (await conn.execute(sql, args)).fetchone()


async def many(conn, sql, args=()):
    return await (await conn.execute(sql, args)).fetchall()
