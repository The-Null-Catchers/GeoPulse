"""Real HTTP GPS producer. No dashboard mock transport and no hidden device credentials."""

import argparse
import asyncio
import math
import os
import random
import statistics
import time
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import httpx
from geospatial import distance

PATH = [
    (34.449, 31.501),
    (34.456, 31.510),
    (34.465, 31.516),
    (34.473, 31.512),
    (34.468, 31.502),
    (34.459, 31.497),
    (34.449, 31.501),
]


def path_point(progress):
    lengths = [distance(a, b) for a, b in zip(PATH, PATH[1:], strict=False)]
    progress %= sum(lengths)
    for a, b, length in zip(PATH, PATH[1:], lengths, strict=False):
        if progress <= length:
            t = progress / length
            bearing = (math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) + 360) % 360
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, bearing
        progress -= length
    return *PATH[0], 0


async def authenticate(client, args):
    if not args.email or not args.password:
        raise SystemExit("Set SIMULATOR_EMAIL and SIMULATOR_PASSWORD or pass --email and --password.")
    if args.seed:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": args.email,
                "password": args.password,
                "name": "Demo operator",
                "organization": "GeoPulse Demo Fleet",
            },
        )
        if response.status_code not in (201, 409):
            response.raise_for_status()
    response = await client.post("/api/v1/auth/login", json={"email": args.email, "password": args.password})
    response.raise_for_status()
    auth = response.json()
    wid = args.workspace or auth["workspaces"][0]["id"]
    return {"Authorization": "Bearer " + auth["access_token"], "X-Workspace-ID": wid}


async def run(args):
    random.seed(args.seed_number)
    async with httpx.AsyncClient(
        trust_env=False, base_url=args.url, timeout=30, limits=httpx.Limits(max_connections=120)
    ) as client:
        headers = await authenticate(client, args)
        if args.seed:
            for table, name in [("teams", "Central delivery"), ("drivers", "Demo driver"), ("vehicles", "Demo van")]:
                r = await client.post("/api/v1/" + table, headers=headers, json={"name": name})
                r.raise_for_status()
            r = await client.post(
                "/api/v1/geofences",
                headers=headers,
                json={"name": "Central depot", "center": [34.46, 31.51], "radius_m": 450, "dwell_seconds": 30},
            )
            r.raise_for_status()
        devices = []
        for i in range(args.devices):
            r = await client.post(
                "/api/v1/devices", headers=headers, json={"name": f"Sim {i + 1:03d} · {args.scenario}"}
            )
            r.raise_for_status()
            devices.append(r.json())
        latencies = []
        errors = 0
        accepted = 0
        duplicates = 0
        started = time.monotonic()
        tick = 0
        semaphore = asyncio.Semaphore(100)

        async def send(i, dev, tick):
            nonlocal errors, accepted, duplicates
            elapsed = time.monotonic() - started
            if args.scenario == "offline" and i == 0 and elapsed > 10:
                return
            if args.scenario == "connectivity" and int(elapsed) % 40 < 15:
                return
            movement_speed = 35 if args.scenario == "speed" and i == 0 else args.speed
            lng, lat, bearing = path_point(elapsed * movement_speed + i * 65)
            if args.scenario == "deviation" and i == 0:
                lng += 0.006
            noise = args.noise / 111000
            lng += random.gauss(0, noise)
            lat += random.gauss(0, noise)
            battery = max(0, 100 - elapsed * 0.01 - i * 0.2)
            if args.scenario == "battery" and i == 0:
                battery = 8
            points = []
            for j in range(args.batch):
                points.append(
                    {
                        "event_id": str(uuid4()),
                        "recorded_at": (
                            datetime.now(timezone.utc) - timedelta(seconds=(args.batch - j - 1) * args.interval)
                        ).isoformat(),
                        "lng": lng,
                        "lat": lat,
                        "speed": movement_speed,
                        "bearing": bearing,
                        "accuracy": max(5, args.noise * 2),
                        "battery_level": battery,
                        "source": "simulator",
                    }
                )
            async with semaphore:
                before = time.perf_counter()
                try:
                    r = await client.post(
                        "/api/v1/locations/batch",
                        headers={"Authorization": "Bearer " + dev["token"]},
                        json={"points": points},
                    )
                    r.raise_for_status()
                    result = r.json()
                    accepted += result["inserted"]
                    duplicates += result["duplicates"]
                    latencies.append((time.perf_counter() - before) * 1000)
                except httpx.HTTPError:
                    errors += 1

        print(f"Created {len(devices)} devices. Sending real GPS points to {args.url}; Ctrl+C to stop.")
        while not args.seconds or time.monotonic() - started < args.seconds:
            before = time.monotonic()
            await asyncio.gather(*(send(i, dev, tick) for i, dev in enumerate(devices)))
            tick += 1
            if tick % 10 == 0:
                print(f"ticks={tick} accepted={accepted} errors={errors}")
            await asyncio.sleep(max(0, args.interval - (time.monotonic() - before)))
        values = sorted(latencies)
        report = {
            "devices": args.devices,
            "duration_s": round(time.monotonic() - started, 2),
            "requests": len(values),
            "accepted_points": accepted,
            "duplicate_points": duplicates,
            "errors": errors,
            "http_p50_ms": round(statistics.median(values), 2) if values else None,
            "http_p95_ms": round(values[min(len(values) - 1, int(len(values) * 0.95))], 2) if values else None,
            "measurement": "client HTTP acceptance, not end-to-end WebSocket or database processing latency",
        }
        import json

        print(json.dumps(report, indent=2))
        if args.output:
            from pathlib import Path

            Path(args.output).write_text(json.dumps(report, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=os.getenv("API_URL", "http://localhost:8000"))
    p.add_argument("--email", default=os.getenv("SIMULATOR_EMAIL"))
    p.add_argument("--password", default=os.getenv("SIMULATOR_PASSWORD"))
    p.add_argument("--workspace", default=os.getenv("WORKSPACE_ID"))
    p.add_argument("--devices", type=int, default=10)
    p.add_argument("--interval", type=lambda s: float(s.removesuffix("s")), default=2)
    p.add_argument("--seconds", type=int, default=0)
    p.add_argument("--speed", type=float, default=8)
    p.add_argument("--noise", type=float, default=3)
    p.add_argument("--batch", type=int, default=1)
    p.add_argument(
        "--scenario", choices=["normal", "offline", "speed", "deviation", "battery", "connectivity"], default="normal"
    )
    p.add_argument("--seed", action="store_true")
    p.add_argument("--seed-number", type=int, default=42)
    p.add_argument("--output")
    args = p.parse_args()
    if not 1 <= args.devices <= 1000 or args.interval < 0.5 or not 1 <= args.batch <= 500:
        p.error("devices 1..1000, interval >= .5s, batch 1..500")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("Simulator stopped.")


if __name__ == "__main__":
    main()
