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

## Not verified

- Updated webhook worker Docker image and Compose startup await the next CI run. The initial remote run successfully built both images and started the original stack.
- Full green GitHub Actions run: the initial run passed backend, web, Docker and secret scanning. Dependency, browser and Flutter findings are repaired in the next commit and require rerun.
- Flutter analyzer and SQLite queue test passed remotely. Widget test timed out on FFI I/O inside fake time; the test is repaired and awaits rerun. Hardware/background tests remain unverified.
- Browser E2E: initial remote mobile-layout login passed; live-socket scenario failed. The API image lacked its WebSocket runtime dependency; it is now included. Full rerun and screenshots pending.
- OSRM image and actual road dataset: adapter implemented, live provider validation pending.
- Independent security/dependency/secret scans and production HTTPS deployment.

## Implementation roadmap status

| Requested phase | Status |
|---|---|
| 1: architecture/infra/auth/workspaces/RBAC | Implemented source; Docker build/initial Compose verified; full green CI pending |
| 2: devices/GPS/persistence/simulator/map | Core implemented and backend integration-tested |
| 3: realtime/presence/states/details | Core tested; expanded filters/scale/backpressure pending |
| 4: history/trips/stops/replay | Core implemented; late-derived reconciliation and event overlays pending |
| 5: geofences/events/alerts | Core implemented and tested; richer alert-rule workflows pending |
| 6: routes/assignment/deviation/ETA | Core implemented; OSRM live validation and missed-stop/late-arrival workflows pending |
| 7: optimization/spatial queries/analytics | Haversine heuristic, nearby API and heatmap; full spatial queries/analytics pending |
| 8: Flutter/background/offline | Foreground source and queue foundation; background/hardware work pending |
| 9: webhooks/reports/keys/audit | Keys/audit/saved-view APIs/trip CSV implemented; signed durable webhooks implemented; more exports pending |
| 10: performance/partitioning/security | 100-device test and regression controls; partitioning/soak/external security pending |
| 11: E2E/CI/Docker/monitoring | Remote checks running; browser/mobile repairs await rerun |
| 12: portfolio/release | Architecture/docs/evidence present; verified screenshots/demo/release pending |

## Continue from here

Keep the repository and migrations intact. Run remote CI first, repair Flutter/browser/Docker findings, capture real dashboard screenshots, and validate self-hosted OSRM. Then implement offline historical reconciliation , expand management workflows, complete mobile background tracking with visible OS-compliant state, and run 1,000-device/historical-data soak tests. Do not mark phases complete merely because schemas/pages exist.
