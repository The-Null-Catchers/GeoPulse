# Validation — source milestone v0.1.0

## Passed locally

- 22 backend tests, including real PostgreSQL/PostGIS and Redis integration (no SQLite stand-in).
- GPS validation, finite/bounded coordinates, timezone/future time validation, simulator movement and distance units.
- Unique device event deduplication, persisted old points and monotonic current snapshots.
- Workspace REST isolation, nearby-radius isolation, foreign-tenant relationship rejection and viewer write denial.
- Circle geofence enter/dwell/exit and rejection of self-intersecting polygon topology.
- Trip start/completion, detected stop, actual route distance deviation and baseline ETA.
- Refresh rotation/reuse family revocation, scoped API key revocation and history erasure.
- WebSocket authorization ticket consumed once, live event delivery.
- Python Ruff and mypy checks.
- Web TypeScript check, production Next.js build and timestamp/gap replay tests.
- Real 100-device / 3-subscriber load scenario, exact evidence in `load-test-result.json`.

The FastAPI TestClient emitted a deprecation notice for its current httpx adapter; tests passed. Updating that test adapter is a maintenance task, not a waived failure.

## Not verified

- Docker image builds and Compose startup on Docker Engine: Docker is unavailable in the current environment.
- GitHub Actions: workflow added, no remote run or merge performed.
- Flutter analyze/unit/widget/hardware/background tests: Flutter SDK is unavailable here. Mobile source is an initial foundation and may need analyzer fixes.
- Browser Playwright specs and screenshots: Chromium download returned invalid/truncated archives. Browser E2E and visual QA are unexecuted, not marked passed.
- OSRM image and actual road dataset: adapter implemented, live provider validation pending.
- Independent security/dependency/secret scans and production HTTPS deployment.

## Implementation roadmap status

| Requested phase | Status |
|---|---|
| 1: architecture/infra/auth/workspaces/RBAC | Implemented source; production Docker execution and external CI pending |
| 2: devices/GPS/persistence/simulator/map | Core implemented and backend integration-tested |
| 3: realtime/presence/states/details | Core tested; expanded filters/scale/backpressure pending |
| 4: history/trips/stops/replay | Core implemented; late-derived reconciliation and event overlays pending |
| 5: geofences/events/alerts | Core implemented and tested; richer alert-rule workflows pending |
| 6: routes/assignment/deviation/ETA | Core implemented; OSRM live validation and missed-stop/late-arrival workflows pending |
| 7: optimization/spatial queries/analytics | Haversine heuristic, nearby API and heatmap; full spatial queries/analytics pending |
| 8: Flutter/background/offline | Foreground source and queue foundation; background/hardware work pending |
| 9: webhooks/reports/keys/audit | Keys/audit/saved-view APIs/trip CSV implemented; webhooks/more exports pending |
| 10: performance/partitioning/security | 100-device test and regression controls; partitioning/soak/external security pending |
| 11: E2E/CI/Docker/monitoring | Source configured; external/browser/mobile execution pending |
| 12: portfolio/release | Architecture/docs/evidence present; verified screenshots/demo/release pending |

## Continue from here

Keep the repository and migrations intact. Run remote CI first, repair Flutter/browser/Docker findings, capture real dashboard screenshots, and validate self-hosted OSRM. Then implement offline historical reconciliation and signed/retried webhooks, expand management workflows, complete mobile background tracking with visible OS-compliant state, and run 1,000-device/historical-data soak tests. Do not mark phases complete merely because schemas/pages exist.
