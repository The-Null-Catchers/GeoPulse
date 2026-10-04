"""Dedicated network dispatcher so slow webhook receivers never stall spatial processing."""

import asyncio
import logging
import signal
from datetime import datetime, timezone
from geopulse.config import settings
from geopulse.db import pool, redis
from geopulse.webhooks import deliver_once


async def run():
    settings.validate()
    await pool.open(wait=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        while not stop.is_set():
            try:
                await redis.set("webhook-worker:heartbeat", datetime.now(timezone.utc).isoformat(), ex=30)
                if not await deliver_once():
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=0.5)
                    except asyncio.TimeoutError:
                        pass
            except Exception:
                logging.exception("Webhook dispatch failed; leased job will recover")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass
    finally:
        await pool.close()
        await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
