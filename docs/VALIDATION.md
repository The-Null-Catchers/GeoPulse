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
| 3: realtime/presence/states/details | Core tested; Combined fleet filters implemented; scale/backpressure pending |
| 4: history/trips/stops/replay | Core implemented; late-derived reconciliation and event overlays pending |
| 5: geofences/events/alerts | Core implemented and tested; richer alert-rule workflows pending |
| 6: routes/assignment/deviation/ETA | Core implemented; OSRM live validation and missed-stop/late-arrival workflows pending |
| 7: optimization/spatial queries/analytics | Haversine heuristic, nearby API, spatial search workflows and heatmap; advanced analytics pending |
| 8: Flutter/background/offline | Foreground source and queue foundation; background/hardware work pending |
| 9: webhooks/reports/keys/audit | Keys/audit/saved-view APIs/trip CSV implemented; signed durable webhooks implemented; more exports pending |
| 10: performance/partitioning/security | 100-device test and regression controls; partitioning/soak/external security pending |
| 11: E2E/CI/Docker/monitoring | All seven remote jobs passed; native rendering and realtime E2E verified |
| 12: portfolio/release | Architecture/docs and verified screenshot present; hosted demo and full production release pending |

## Continue from here

Validate self-hosted OSRM against a real regional dataset, implement offline historical reconciliation, expand management workflows, complete mobile background tracking with visible OS-compliant state, and run 1,000-device/historical-data soak tests. Preserve migrations and history. Do not mark phases complete merely because schemas/pages exist.

## Fleet filter increment

The dashboard combines name, all derived statuses, team (including unassigned), device type and activation. The same filtered snapshot feeds native map layers, fit bounds, fleet list and device registry. Filters reset on sign-out/sign-in; workspace metrics retain their existing workspace scope. Counts explicitly describe loaded devices: this UI currently loads the first 1,000 device records and 1,000 teams rather than claiming a complete larger fleet search.

Local validation: TypeScript checking, seven web unit tests and production build. Added Playwright coverage checks native marker removal/restoration and intersecting team/type/activation/search filters, including inactive devices without GPS and session reset. Browser execution is recorded by CI; local Docker integration is unavailable in this workspace.

## Spatial operations increment

Added closest-device, Polygon/MultiPolygon device coverage, route-corridor device queries, enabled geofences containing a point, and dated nearby-stop searches. The map page renders search results using native sources/layers and exposes bounded result paging independently of the loaded fleet. Migration 004 adds indexes for geometry-cast snapshot queries and stop searches. Read-only API keys and viewer users can use the POST polygon query without gaining mutation permission.

Local validation: Ruff, mypy, TypeScript, seven web unit tests, and 49 Python tests passed. Four new real-PostGIS integration cases cover boundaries/holes, paging, metric distance/radius, inactive devices, tenant isolation, foreign routes, read-only API keys, invalid polygon topology, disabled fences and stop time windows. Local execution skips 14 integration tests because this workspace has no running PostGIS/Redis. A new Playwright scenario checks actual ingested GPS and containing fences rendered in native layers, area queries and invalidation after changing the search point. All seven jobs passed on run 37636077750 for commit 6c8848e, including 63 real-PostGIS backend tests and four browser scenarios. The spatial search increment is remotely verified.

## Historical replay increment

Added separate keyset-paged point/event APIs with tenant checks and a seven-day range cap. The web player automatically loads bounded history, accepts UTC start/end times, exposes stop arrival/departure, fence enter/exit/dwell and alert-created events, and seeks directly from the timeline. Native event markers follow playback time. Alert positions explicitly retain their last-known GPS timestamp or remain unpositioned when no previous point exists. The route trail splits at GPS gaps rather than connecting missing travel. Binary search handles timestamp ties and interpolation; request generations invalidate history after input/session changes or a history-deletion broadcast.

New unit coverage exercises cursor paging, explicit truncation, cancellation, timestamp ties, bearing wrap and disconnected trails. New PostGIS coverage verifies equal-time cursors, more than 5,000 persisted points, workspace isolation, event cursor ties, stop durations, no invented alert locations and deletion. A new browser scenario ingests actual GPS to produce stop/fence events, seeks the player and verifies native event layers and range invalidation. Local checks passed: 49 Python tests (16 integration scenarios skipped), Ruff, mypy, TypeScript, 13 web tests and a production build. Local PostGIS/browser execution remains unavailable; see the replay PR's CI for remote results.

The replay history-erasure regression exposed geofence events without a `location_id` surviving the old GPS-cascade-only deletion. Device erasure now explicitly removes all device geofence events; worker retention also expires unlinked events by their recorded time.

Remote validation: all seven jobs passed on run 37637940009 for commit 2ef813c. This includes 66 backend tests against PostGIS/Redis, 13 web unit tests, five Playwright scenarios, Flutter checks, Docker builds and security scans. Visual review of the generated replay screenshot then identified narrow controls in the map panel; the controls now wrap with minimum readable widths and screenshot capture returns to the top of the page.
