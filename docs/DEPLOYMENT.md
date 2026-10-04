# Deployment

## Local demonstration

1. Install Docker/Compose v2, then run `python3 scripts/init-env.py`.
2. Run `docker compose up -d --build --wait`. A one-shot migration service applies versioned SQL before API/worker start.
3. Run `docker compose run --rm simulator` to register the demo and stream real updates.
4. Visit `http://localhost`; use generated simulator credentials from `.env`.
5. Inspect `docker compose logs -f api worker simulator` without publishing them unredacted.

Ports: Caddy 80/443, API 8000 and web 3000 on host loopback only. PostGIS and Redis are internal. App health endpoints `/health` and `/ready` separate liveness from database/Redis availability. Worker heartbeat healthcheck detects a stalled or disconnected loop. PostGIS, Redis and Caddy use named persistent volumes.

## HTTPS environment

Set `SITE_ADDRESS=geo.example.org`, point its DNS at your host, set `CORS_ORIGINS=https://geo.example.org`, and `COOKIE_SECURE=true`. Caddy manages HTTPS. Replace generated demo credentials or omit simulator variables for a production deployment. Keep `.env` outside git, mode 0600, and source deployment secrets through your host's secret manager where available. `JWT_SECRET` must be at least 32 characters; generated value is longer.

Configure resource limits and host firewalls, automated database backups, tested restore, alerting and tile-provider terms before serving real operational data. Restrict access to the internal API/metrics network. Monitor outbox age, not only API HTTP health. Migration rollback is not automated; test migrations on a restored staging backup before deployment. No production host or remote CI deployment was performed in this milestone.

## Routing data

`routing` is optional and off by default. Obtain an appropriate `.osm.pbf` regional extract under your license and prepare a version-compatible OSRM MLD dataset in `routing-data`:

```sh
mkdir -p routing-data
# Place your region.osm.pbf here first.
docker run --rm -v "$PWD/routing-data:/data" ghcr.io/project-osrm/osrm-backend:v5.27.1 \
  osrm-extract -p /opt/car.lua /data/region.osm.pbf
docker run --rm -v "$PWD/routing-data:/data" ghcr.io/project-osrm/osrm-backend:v5.27.1 \
  osrm-partition /data/region.osrm
docker run --rm -v "$PWD/routing-data:/data" ghcr.io/project-osrm/osrm-backend:v5.27.1 \
  osrm-customize /data/region.osrm
```

Set `ROUTING_URL=http://routing:5000`, then run `docker compose --profile routing up -d`. The required full dataset consists of multiple `.osrm*` files; do not mount only the main file. Route API returns 503 when engine is absent/unavailable and 422 for no usable road route. Dataset processing and image execution have not been verified in this environment.

## Monitoring

`docker compose --profile monitoring up -d` starts Prometheus on loopback 9090. Metrics include pending outbox count/age, worker heartbeat age and approximate connected WebSockets. Grafana dashboards, system exporters, request-duration histograms and error-reporting integration are pending. Prometheus is not a substitute for PostgreSQL backup/restore monitoring.

## Mobile

Follow `apps/mobile/README.md`, generate platform folders, run `python3 scripts/mobile-bootstrap.py`, then analyze/test and verify consent, GPS, loss/reconnect and stop controls on physical Android/iOS devices. Do not publish the Flutter application as background-capable until platform services and lifecycle tests are implemented.
