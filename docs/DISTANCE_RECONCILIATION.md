# Late GPS and daily distance

Offline batches preserve original GPS timestamps. The live processor still ignores older or equal-time samples for presence, position, trips, geofences and route checks. It now durably schedules distance repair for that UTC day and its successor in the same transaction as processing the sample. Migration 006 stores jobs with a device/workspace/day primary key, so repeated late points coalesce.

## Calculation and delivery

The worker repairs one device-day per transaction, after that device's unprocessed location outbox has drained. It also checks jobs during idle loops and every maintenance cycle. PostgreSQL device locks serialize repairs against ingestion and history erasure; the processor's advisory lock prevents concurrent incremental metric writes. A second job check after obtaining the device lock prevents an erased job from recreating history.

PostGIS calculates spheroidal `ST_Distance` in meters between timestamp-ordered samples. Equal timestamps use the smallest event UUID as a deterministic canonical sample. Segments must have a positive duration no greater than the workspace's `offline_seconds`; jumps exceeding `150 * seconds + accuracy` meters are excluded, matching the live distance guard. The incoming segment belongs to its ending sample's UTC day. A lookback of `offline_seconds` includes the preceding sample at midnight. The configuration caps this threshold at 86,400 seconds, so a late point can change only its own day and the following day.

The worker replaces each daily metric rather than adding it, and changes only the distance field of a matching current device snapshot. Position, timestamp, operational state and alerts never rewind. Updating metrics, removing the job and emitting `metrics.updated` into the transactional outbox commit together. Database/publication failures roll back and retain the job for retry. Redis delivery uses the existing at-least-once outbox. The dashboard refreshes metrics on that event and every 30 seconds.

## REST and dashboard

- `GET /api/v1/analytics/distance?start=2026-10-01&end=2026-10-07&device_id=<uuid>` returns up to 90 inclusive UTC days, including zero-activity days. Omit `device_id` for workspace totals. Each row includes `date`, `distance_m` and `pending_devices`.
- `POST /api/v1/analytics/distance/recalculate?start=2026-10-01&end=2026-10-07&device_id=<uuid>` queues an administrative backfill of retained data, including a successor day. It requires Admin/Owner authorization, logs an audit action, rejects future dates and returns 202 only after jobs persist. Requests coalesce.
- Both endpoints validate tenant ownership. Read-scoped API keys can fetch aggregates but cannot request a rebuild.
- Analytics shows daily distance, relative activity meters, a device/date filter and pending recalculation. Device options currently use the dashboard's first 1,000 loaded devices; entire-workspace aggregate queries have no such fleet limit.
- Overview's distance total now uses daily metrics instead of trip distances; device lists show zero for yesterday's cached total.

## Privacy, scale and limits

Device deletion cascades jobs; explicit history erasure removes them under the same device lock as raw/derived history. Repairs discard dates outside retention. Queries read one device-day plus a bounded lookback using the existing workspace/device/time index, run with a ten-second statement timeout and keep data inside PostgreSQL. This bounds calendar work, not the number of points in an unusually dense device-day. Sustained ingestion can postpone repairs until the device queue drains; pending counters disclose this. Chunked aggregation, fairness for repeated timeouts and a large-dataset soak remain future scale work.

This increment repairs **distance metrics**, not historical trip/stop boundaries, geofence transitions, route assignments or past alerts. Those remain arrival-order derived and need a separately versioned historical reconciliation strategy. No retroactive alerts/webhooks are invented. Equal-time live position uses the first processed sample, whereas aggregate distance is deterministic by event UUID. GPS distance is sampled movement, not odometer distance or a matched road route.

## Validation

Real-PostGIS tests cover a late detour, duplicate retry, replacement backfill, UTC midnight, continuity gaps, impossible jumps, pending-location deferral, history erasure, tenant isolation, read-key permission, range validation and rollback/retry. Playwright uploads actual out-of-order GPS, observes the corrected daily total in the dashboard and checks that the live position stays at the latest sample. Local checks skip integration tests when PostGIS/Redis are unavailable; remote CI evidence is recorded on the PR.
