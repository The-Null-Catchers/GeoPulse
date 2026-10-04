"""Deterministic algorithms. Network routing is deliberately a separate adapter."""

import math


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """WGS84 spherical distance in metres; coordinates are longitude, latitude."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def optimize(
    points: list[tuple[float, float]], start: tuple[float, float], end: tuple[float, float] | None = None
) -> dict:
    """Nearest neighbour + open-path 2-opt, fixed endpoints; NOT a road travel-time optimizer."""
    remaining = set(range(len(points)))
    order: list[int] = []
    current = start
    while remaining:
        index = min(remaining, key=lambda i: (distance(current, points[i]), i))
        remaining.remove(index)
        order.append(index)
        current = points[index]

    def cost(seq):
        path = [start] + [points[i] for i in seq] + ([end] if end is not None else [])
        return sum(distance(a, b) for a, b in zip(path, path[1:], strict=False))

    baseline = cost(order)
    for _ in range(50):
        improved = False
        for i in range(len(order)):
            for j in range(i + 2, len(order) + 1):
                candidate = order[:i] + list(reversed(order[i:j])) + order[j:]
                if cost(candidate) + 0.01 < cost(order):
                    order = candidate
                    improved = True
        if not improved:
            break
    return {
        "order": order,
        "distance_m": round(cost(order), 1),
        "initial_distance_m": round(baseline, 1),
        "algorithm": "haversine-nearest-neighbor-2opt",
    }


def state(
    speed: float,
    last_seen_age: float,
    stationary_seconds: float,
    offline_seconds: float = 120,
    moving_speed: float = 1.5,
    stop_seconds: float = 180,
) -> str:
    if last_seen_age > offline_seconds:
        return "offline"
    if speed > moving_speed:
        return "moving"
    return "stopped" if stationary_seconds >= stop_seconds else "idle"
