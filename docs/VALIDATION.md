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

[Run 37239362834](https://github.com/The-Null-Catchers/GeoPulse/actions/runs/37239362834), commit `f198289`: all seven jobs passed (backend, web, Flutter, Docker, Playwright, dependency audit and secret scan). Compose included the webhook dispatcher. Flutter analyze and both tests passed. Playwright authenticated a real workspace, ingested GPS, observed the live connection and persisted position, and checked phone sign-in layout.

Visual inspection of the resulting screenshot exposed a CARTO key watermark despite passing functional tests. The next commit replaces that unconfigured dependency with a configurable XYZ basemap and adds a second GPS update with device-list resync blocked. This follow-up requires its own green run and new visual review.

## Not verified

- Mobile hardware/background operation and Android/iOS release builds remain unverified.
- Configurable basemap visual review and strengthened realtime E2E await the follow-up run.
- OSRM image and actual road dataset: adapter implemented, live provider validation pending.
- Independent security/dependency/secret scans and production HTTPS deployment.

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
| 11: E2E/CI/Docker/monitoring | All seven remote jobs passed; visual/realtime follow-up underway |
| 12: portfolio/release | Architecture/docs/evidence present; verified screenshots/demo/release pending |

## Continue from here

Keep the repository and migrations intact. Run remote CI first, repair Flutter/browser/Docker findings, capture real dashboard screenshots, and validate self-hosted OSRM. Then implement offline historical reconciliation , expand management workflows, complete mobile background tracking with visible OS-compliant state, and run 1,000-device/historical-data soak tests. Do not mark phases complete merely because schemas/pages exist.
