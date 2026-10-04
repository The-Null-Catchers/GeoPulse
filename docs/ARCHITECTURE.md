# Architecture

## Boundaries

FastAPI handles identity, workspace authorization, validation, ingestion and spatial read APIs. A separate Python worker handles derived operational state. PostgreSQL is the authority. Redis carries ephemeral realtime events, rate limits, short-lived WebSocket tickets and worker heartbeat. MapLibre renders GeoJSON via native sources/layers. Flutter sends explicit, foreground-only GPS samples; its operator screen presently polls.

The monorepo avoids a framework-heavy abstraction layer: SQL is explicit, parameterized and versioned. Dynamic table identifiers use `psycopg.sql.Identifier` and a fixed internal registry. Team/driver/vehicle/device/route/fence cross-relations use `(workspace_id,id)` constraints to prevent cross-tenant associations even if an application check regresses. REST selectors always constrain workspace IDs. Authorization does not trust IDs provided by the browser.

## Decisions

1. **PostGIS geography for GPS and routes**: meter-based distance and radius semantics. Geofences are geometry(MultiPolygon,4326) for cover predicates; circle buffers are generated in geography then converted. Longitudes precede latitudes.
2. **Transactional outbox rather than a persistence/pubsub dual write**: ingestion commits points and pending events together. Redis failure cannot discard the processing request. The processed payload is committed before publication. Publication acknowledgement is separately committed, so duplicates are possible and carry stable IDs.
3. **Ordered single spatial processor in this milestone**: an advisory lock serializes processing transactions. Multi-worker per-device partitioning is not implemented. Launch one worker for this release. This favors demonstrated correctness over unjustified horizontal scale claims.
4. **No SQLite substitution for geospatial integration**: integration tests explicitly require real PostGIS and Redis.
5. **Road routing is an adapter**: absent/unavailable OSRM returns 503, not a straight line mislabeled as a road route. Stop optimization is a separately labeled spherical-distance heuristic.
6. **Mobile privacy before background service work**: collection stops on pause/detach and requires explicit consent and OS permission. Background tracking is not claimed until lifecycle, platform integration and physical-device tests exist.

## Transaction paths

Each ingestion batch locks its device, rechecks activation and inserts accepted unique events plus outbox rows. Batches are sorted by recorded time and event UUID. Processing locks the device and checks whether the point is newer than its current snapshot. A newer point can produce a status snapshot, metrics, trip/stop transitions, fence events, alerts and route deviation/ETA in one transaction.

A point older than or equal to the latest snapshot persists in raw history but does not reverse current state. It emits `history.updated` and is available for timestamp-ordered replay. Rebuilding derived historical events after offline backfill is a remaining requirement. Thus raw-history correctness should not be confused with fully reconciled historical analytics.

## Model coverage

The initial migration includes all requested core entities: users, organizations, memberships, teams, devices, drivers, vehicles, locations, status, fences/events, routes/assignments, trips, stops, alerts/rules, commands, snapshots, metrics, saved views, audit logs, API keys. Refresh sessions, invitations, geofence state and outbox provide supporting infrastructure. Commands and snapshots are schema foundations rather than complete feature lifecycles.

UTC is configured on pooled PostgreSQL connections. GPS samples retain original timestamps and a separate server receive timestamp. Event UUIDs are deduplicated per device independently of event time.
