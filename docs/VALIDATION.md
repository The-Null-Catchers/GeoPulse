# Validation — source milestone v0.1.0

## Passed locally

- 50 backend tests, including real PostgreSQL/PostGIS and Redis integration (no SQLite stand-in).
- GPS validation, finite/bounded coordinates, timezone/future time validation, simulator movement and distance units.
- Unique device event deduplication, persisted old points and monotonic current snapshots.
- Workspace REST isolation, nearby-radius isolation, foreign-tenant relationship rejection and viewer write denial.
- Circle geofence enter/dwell/exit and rejection of self-intersecting polygon topology.
- Trip start/completion, detected stop, actual route distance deviation and baseline ETA.
- Refresh rotation/reuse family revocation, scoped API key revocation and history erasure.
- WebSocket authorization ticket consumed once, live event delivery.
- Signed webhook transport using a real TLS receiver, persisted 503→204 retries, stable IDs, signature verification, public DNS pinning, tenant isolation and history erasure.
- Python Ruff and mypy checks.
- Web TypeScript check, production Next.js build and timestamp/gap replay tests.
- Real 100-device / 3-subscriber load scenario, exact evidence in `load-test-result.json`.

The FastAPI TestClient emitted a deprecation notice for its current httpx adapter; tests passed. Updating that test adapter is a maintenance task, not a waived failure.

## Remote CI evidence

[Run 37240412037](https://github.com/The-Null-Catchers/GeoPulse/actions/runs/37240412037), code commit `f1fa82d`: all seven jobs passed (backend, web, Flutter, Docker, Playwright, dependency audit and secret scan). Compose includes the webhook dispatcher. Flutter analyze and both queue/widget tests passed. Backend ran 50 tests against PostGIS/Redis; web ran four replay tests and a production build.

Playwright authenticated a workspace, ingested two actual GPS events, blocked device-list resync before the second update, and observed the new position over WebSocket. It checks that native MapLibre layers contain rendered fleet features and that no worker-load errors occurred. The screenshot in `docs/screenshots/live-operations.png` comes from that exact run; visual inspection confirmed a readable basemap and GPS marker. The responsive phone sign-in test also passed. This is functional/visual evidence from a Docker integration environment, not physical-device validation or a production deployment.

## Not verified

- Mobile hardware/background operation and Android/iOS release builds remain unverified.
- OSRM image and actual road dataset: adapter implemented, live provider validation pending.
- Independent manual security review/penetration testing and production HTTPS deployment. Automated dependency audits and secret scanning passed.

## Implementation roadmap status

| Requested phase | Status |
|---|---|
| 1: architecture/infra/auth/workspaces/RBAC | Implemented source; Docker/Compose and CI verified; production deployment pending |
| 2: devices/GPS/persistence/simulator/map | Core implemented and backend integration-tested |
| 3: realtime/presence/states/details | Core tested; expanded filters/scale/backpressure pending |
| 4: history/trips/stops/replay | Core implemented; late-derived reconciliation and event overlays pending |
| 5: geofences/events/alerts | Core implemented and tested; richer alert-rule workflows pending |
| 6: routes/assignment/deviation/ETA | Core implemented; OSRM live validation and missed-stop/late-arrival workflows pending |
| 7: optimization/spatial queries/analytics | Haversine heuristic, nearby API and heatmap; full spatial queries/analytics pending |
| 8: Flutter/background/offline | Foreground source and queue foundation; background/hardware work pending |
| 9: webhooks/reports/keys/audit | Keys/audit/saved-view APIs/trip CSV implemented; signed durable webhooks implemented; more exports pending |
| 10: performance/partitioning/security | 100-device test and regression controls; partitioning/soak/external security pending |
| 11: E2E/CI/Docker/monitoring | All seven remote jobs passed; native rendering and realtime E2E verified |
| 12: portfolio/release | Architecture/docs and verified screenshot present; hosted demo and full production release pending |

## Continue from here

Validate self-hosted OSRM against a real regional dataset, implement offline historical reconciliation, expand management workflows, complete mobile background tracking with visible OS-compliant state, and run 1,000-device/historical-data soak tests. Preserve migrations and history. Do not mark phases complete merely because schemas/pages exist.
