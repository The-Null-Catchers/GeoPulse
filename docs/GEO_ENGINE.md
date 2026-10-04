# Geospatial engine

## Units, types and indexes

- Coordinates: WGS84 EPSG:4326, GeoJSON ordering `[longitude, latitude]`.
- GPS/status/stops: `geography(Point,4326)`.
- Planned routes: `geography(LineString,4326)`.
- Geofences: `geometry(MultiPolygon,4326)`; `ST_Covers` includes boundary points.
- GiST indexes on raw GPS, current status, fences and routes. Device/time B-tree index and recorded-time BRIN support time-series reads.
- Radius queries use `ST_DWithin(geography, geography, meters)`; [PostGIS documentation](https://postgis.net/docs/ST_DWithin.html).

## Ingestion rules

Coordinates must be finite and within world bounds. Timestamps must include a timezone and may be at most 5 minutes ahead. Speed is meters/second, bearing degrees clockwise from north, accuracy meters and battery percent. Accuracy above 200m and points older than retention are filtered, with counts returned. Each batch accepts up to 500 records. It is one atomic database transaction, currently using per-point statements rather than COPY/bulk inserts. Conflicting `(device_id,event_id)` UUIDs are treated as duplicates; producers must never reuse a UUID for changed content.

## Status, trips and stops

Default moving speed: >1.5m/s. Offline: receive/heartbeat age >120s. A device below moving speed with a stable anchor within 30m is idle; after 180s it is stopped. Workspace thresholds are adjustable. Unknown covers devices without accepted GPS. Online covers connected devices without a processed movement classification.

A moving snapshot starts a trip. A confirmed stop closes it; a gap longer than the offline threshold closes an old trip at the previous snapshot before a new movement begins. Consecutive sample distances only count when time separation is within the continuity window and displacement is physically bounded at 150m/s plus accuracy. Daily metrics roll over in UTC. Gaps are not invented as traveled straight lines. A stable stop records the anchor and original stationary arrival, then departure on movement or anchor displacement.

Noise can cause incorrect operational classifications; speed and accuracy are device-provided, not road-matched. There is no guaranteed GPS spoofing detection. First/last trip segment, midnight splitting, irregular sampling and long gaps need broader domain tests before operational billing/reporting use.

## Fences

Circle creation uses `ST_Buffer(geography, radius_m)`; polygon input checks closure, coordinate limits, size and PostGIS validity. Worker evaluates enabled workspace fences. State transitions persist enter/exit/dwell with original recorded timestamps. Dwell fires once per entry, on the first subsequent eligible sample after the duration threshold. It is not a wall-clock timer that fires without new GPS. Excessive dwell generates a real alert; exit resolves that dwell alert. Entry/exit events are stored and broadcast but configurable alerts for all event types are pending.

## Routes and optimization

The OSRM adapter fetches actual road polyline, distance and duration from the configured self-hosted engine. Assignments are unique while active. Deviation compares geography point-to-linestring distance. It must remain beyond the configured distance for the configured duration; a return resolves the alert. Arrival within 30m of the route endpoint completes the current assignment. Intermediate stop completion, missed stops and late-arrival deadlines are pending.

ETA currently equals `OSRM duration * (1 - projected progress)` using `ST_LineLocatePoint` on the WGS84 line. It is a baseline estimate, not a road-distance recalculation from the current point or traffic-aware prediction. Looped routes, off-route positions and out-of-order stop visits need improved progress state before ETA is production-reliable.

The optimizer uses deterministic nearest-neighbour followed by open-path 2-opt with fixed start and optional fixed end. Up to 50 stops and 50 improvement passes are supported. Output includes the permutation, initial and improved Haversine lengths. It does not claim road travel time, capacity constraints, windows or multi-vehicle VRP.

## Replay and analytics

Replay interpolates location/speed against timestamp intervals, supports seek/play/pause and .5/1/2/5/10x speed, and holds position across gaps longer than 120s. Web replay loads at most the first 5,000 points of a UTC day; API pagination supports additional reads but automatic paging is pending. Stop/event/alert timeline overlays remain pending. History is stored in PostGIS, not generated in the browser.

Heatmaps aggregate `ST_SnapToGrid` bins server-side for bounded ranges and return at most 10,000 bins. This reduces client data volume; separate alert/idle/pickup sources and tile-based aggregation are future work.
