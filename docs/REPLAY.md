# Historical replay

Select a device, open Replay, choose a UTC date and start/end time, then load history. Play/pause, timestamp seek and 0.5/1/2/5/10x controls move the marker using recorded GPS intervals. Speed changes and heading wrap are interpolated; gaps over 120 seconds hold the last recorded position. The native route trail also splits at these gaps, so missing travel is not shown as a connected line.

Recorded activity lists persisted stop arrival/departure, geofence enter/exit/dwell and alert-created events. Filter by event category and click an event to seek the player; timestamped native markers appear as the playhead reaches events. Stop departure carries measured duration. Alert positions use the most recent persisted GPS at or before the alert timestamp, disclose that GPS timestamp, and are omitted when no previous point exists. No alert position is synthesized from future GPS. Alert acknowledgement/resolution is not an immutable historical event ledger and is not replayed.

The browser automatically requests keyset pages up to 20,000 points and 5,000 events, with explicit notices if additional pages remain. Narrow the UTC time range to inspect another part of the day. Limits avoid loading an entire large historical dataset into the browser. The event list displays 50 rows at a time. Interpolation uses binary search over ordered timestamps and resolves equal timestamps to the final event-ID-ordered sample. Location history remains device-provided GPS; no road matching is claimed.

## Read APIs

`GET /api/v1/devices/{device_id}/replay/points` and `/replay/events` require `start` and `end`, both timezone-aware, with an end after the start and at most seven days. User membership or a workspace API key with read scope is required alongside `X-Workspace-ID`. Missing and foreign devices both return 404. Disabled devices retain historical read access subject to retention/deletion.

Each response is `{ "items": [...], "next_cursor": null | { "recorded_at": "…", "id": "…" } }`. Pass both returned cursor values as `after_time` and `after_id` to continue. Supplying only one or a cursor outside the requested range returns 422. Point pages default to 1,000 and cap at 5,000; event pages default to 500 and cap at 1,000. No offset scan is required. Points order by `(recorded_at,event_id)`; events order by `(recorded_at,composite_event_id)`. A stop has separate stable arrival and departure IDs so equal timestamps do not duplicate or skip either event.

Ranges are inclusive. Event filtering uses event timestamp: stop arrival/departure, fence recorded time, and an alert's `recorded_at` with `created_at` fallback. This is not a full stop-occupancy interval API: a stop spanning an entire range without arriving/departing in it has no transition in that range. Relevant immutable transition history is read from PostGIS, rather than reconstructed from current dashboard alerts. Migration 005 adds point cursor and operational-event time indexes.

## Consistency and privacy boundaries

Keyset pages are not a database snapshot. A point uploaded after the cursor has passed its older timestamp appears on a reload; it does not shift already-read pages or force a duplicate. Derived trip/stop/fence history is not rebuilt for older out-of-order GPS in this increment. That reconciliation remains a release gate. Concurrent retention/history deletion can change pages; a subsequent load reads the remaining persisted data.

Device/date/time/session changes invalidate outstanding requests and clear loaded history. A `device.history_deleted` WebSocket event also clears replay state. The server checks device ownership on every page. The existing array-returning `/history` API is preserved for compatibility.

## Validation

Unit tests cover tied timestamps, bearing interpolation, split trails, advancing cursors, exact terminal pages, truncation and stale loads. PostGIS integration scenarios page through 5,106 persisted points and verify event tie ordering, stop duration, tenant isolation, explicit cursor validation, history deletion and absent pre-GPS alert positions. Playwright uses real authenticated GPS ingestion to produce stop/geofence events, seeks the timeline, inspects native event layers and verifies range invalidation.
