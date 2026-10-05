"""100-device ingestion + multiple live subscribers. JSON evidence, no fabricated system metrics."""

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import httpx
import websockets


def percentile(values, fraction):
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * fraction))], 2) if ordered else None


async def run(args):
    async with httpx.AsyncClient(
        trust_env=False, base_url=args.url, timeout=30, limits=httpx.Limits(max_connections=150)
    ) as client:
        uid = str(uuid4())[:8]
        r = await client.post(
            "/api/v1/auth/register",
            json={
                "email": uid + "@load.test",
                "name": "Load test",
                "organization": "Load test " + uid,
                "password": str(uuid4()),
            },
        )
        r.raise_for_status()
        auth = r.json()
        headers = {"Authorization": "Bearer " + auth["access_token"], "X-Workspace-ID": auth["workspace_id"]}
        devices = []
        for i in range(args.devices):
            r = await client.post("/api/v1/devices", headers=headers, json={"name": f"Load device {i}"})
            r.raise_for_status()
            devices.append(r.json())
        sent_at = {}
        delivery = []
        http_latencies = []
        errors = []
        received = [0] * args.clients

        async def listen(index):
            r = await client.post("/api/v1/realtime/ticket", headers=headers)
            r.raise_for_status()
            async with websockets.connect(args.ws + "?ticket=" + r.json()["ticket"], origin=args.origin) as socket:
                await socket.recv()
                ready[index].set()
                async for raw in socket:
                    event = json.loads(raw)
                    if event["type"] == "location.updated":
                        received[index] += 1
                        key = (
                            event["data"]["device_id"]
                            + ":"
                            + str(datetime.fromisoformat(event["data"]["recorded_at"]).timestamp())
                        )
                        # API serializes UTC as +00:00, producers use the same encoding.
                        if key in sent_at:
                            delivery.append((time.perf_counter() - sent_at[key]) * 1000)
                    if stop.is_set():
                        break

        ready = [asyncio.Event() for _ in range(args.clients)]
        stop = asyncio.Event()
        subscribers = [asyncio.create_task(listen(i)) for i in range(args.clients)]
        await asyncio.wait_for(asyncio.gather(*(r.wait() for r in ready)), timeout=30)
        started = time.perf_counter()
        accepted = 0

        async def send(i, tick):
            nonlocal accepted
            stamp = datetime.now(timezone.utc).isoformat()
            point = {
                "event_id": str(uuid4()),
                "recorded_at": stamp,
                "lng": 34.46 + i * 0.00001 + tick * 0.00003,
                "lat": 31.51,
                "speed": 8,
                "bearing": 90,
                "accuracy": 5,
                "source": "simulator",
            }
            before = time.perf_counter()
            sent_at[devices[i]["id"] + ":" + str(datetime.fromisoformat(stamp).timestamp())] = before
            try:
                response = await client.post(
                    "/api/v1/locations", headers={"Authorization": "Bearer " + devices[i]["token"]}, json=point
                )
                response.raise_for_status()
                accepted += response.json()["inserted"]
                http_latencies.append((time.perf_counter() - before) * 1000)
            except Exception as e:
                errors.append(str(e))

        for tick in range(args.ticks):
            before = time.perf_counter()
            await asyncio.gather(*(send(i, tick) for i in range(args.devices)))
            await asyncio.sleep(max(0, args.interval - (time.perf_counter() - before)))
        # Explicit drain deadline; report dropped/lagging messages rather than pretending receipt.
        until = time.monotonic() + 30
        while min(received, default=accepted) < accepted and time.monotonic() < until:
            await asyncio.sleep(0.1)
        stop.set()
        for sub in subscribers:
            sub.cancel()
        await asyncio.gather(*subscribers, return_exceptions=True)
        report = {
            "devices": args.devices,
            "websocket_clients": args.clients,
            "ticks": args.ticks,
            "interval_s": args.interval,
            "accepted_points": accepted,
            "http_errors": len(errors),
            "received_per_client": received,
            "elapsed_s": round(time.perf_counter() - started, 2),
            "http_p50_ms": percentile(http_latencies, 0.5),
            "http_p95_ms": percentile(http_latencies, 0.95),
            "websocket_end_to_end_p50_ms": percentile(delivery, 0.5),
            "websocket_end_to_end_p95_ms": percentile(delivery, 0.95),
            "websocket_latency_samples": len(delivery),
            "cpu_usage": None,
            "memory_usage": None,
            "database_query_time_ms": None,
            "environment": "Disposable local PostgreSQL/PostGIS and Redis; single API and worker; not production sizing.",
        }
        print(json.dumps(report, indent=2))
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
        if errors or any(count != accepted for count in received):
            raise SystemExit("Load test delivery/count assertion failed")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--ws", default="ws://localhost:8000/api/v1/realtime")
    p.add_argument("--origin", default="http://localhost:3000")
    p.add_argument("--devices", type=int, default=100)
    p.add_argument("--clients", type=int, default=3)
    p.add_argument("--ticks", type=int, default=10)
    p.add_argument("--interval", type=float, default=2)
    p.add_argument("--output", default="docs/load-test-result.json")
    asyncio.run(run(p.parse_args()))
