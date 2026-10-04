"""Small async Python device SDK. Caller owns durable queue and event UUIDs."""

import httpx


class DeviceClient:
    def __init__(self, url: str, token: str):
        self.client = httpx.AsyncClient(
            trust_env=False, base_url=url, timeout=30, headers={"Authorization": "Bearer " + token}
        )

    async def upload(self, points: list[dict]):
        response = await self.client.post("/api/v1/locations/batch", json={"points": points})
        response.raise_for_status()
        return response.json()

    async def heartbeat(self):
        response = await self.client.post("/api/v1/devices/heartbeat")
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.client.aclose()
