# Spatial search

Open **Spatial Search** in the dashboard. Click the map to pick a point; choose the query and run **Search area**. Results appear as native MapLibre circles or polygon fills and in a timestamped list. A drawn area can be used without saving a geofence; saved geofences can also supply a Polygon/MultiPolygon. Select a planned route to search its corridor. Nearby stops use the selected UTC arrival date. Next/previous results page through matches independently of the first 1,000 devices loaded by the fleet sidebar.

All endpoints require a workspace member or scoped workspace API key, with `Authorization: Bearer …` and `X-Workspace-ID`. Device tokens cannot query operational data. A `read` key can use the POST polygon endpoint because it is a read-only query; it still cannot create devices or geofences. Viewer membership also permits all queries.

| Endpoint under `/api/v1/spatial` | Parameters | Result |
|---|---|---|
| `GET /devices/closest` | `lat`, `lng`, `radius` (default 10,000m) | Closest active snapshot or `null` |
| `POST /devices/in-polygon` | Body `{ "geometry": <GeoJSON Polygon or MultiPolygon> }`; `limit`, `offset` | Active snapshots covered by the geometry |
| `GET /devices/near-route` | `route_id`, `radius` (default 150m); `limit`, `offset` | Active snapshots within the planned route corridor |
| `GET /geofences/containing` | `lat`, `lng`; `limit`, `offset` | Enabled geofences covering the point |
| `GET /stops/nearby` | `lat`, `lng`, `radius` (default 1,000m), `start`, `end`; `limit`, `offset` | Stops whose arrival is in the inclusive time range |

Paged responses have `{ "items": [...], "has_more": boolean }`. The API defaults to 100 results, permits up to 500 per page and offsets up to 100,000. Results have deterministic ID tie-breakers; offset pagination is not a snapshot across concurrent GPS updates. Repeat the search for a fresh operational picture. All distance/radius values are meters; input positions are WGS84 longitude/latitude. Radius must be positive and at most 100,000m; coordinates and radii must be finite. Stop ranges require explicit timezones, an end after the start, and at most 31 days.

Device results expose ID, name, latest processed coordinates and `recorded_at`; closest/corridor results also expose `distance_m`. Stops include `device_id`, device name, arrival/departure and coordinates. Unknown devices without a processed position and inactive devices are excluded from current-device queries. Offline devices with a previous position remain searchable; recorded timestamps disclose staleness. Historical stop search includes deactivated devices so disabling tracking does not silently hide their history. History deletion/retention still applies.

Polygon validation rejects malformed nesting, nonfinite/out-of-range coordinates, unclosed rings, over 5,000 total positions and over 100 polygons. PostGIS validates polygon topology. Boundaries count as covered, holes do not. These are planar WGS84 area semantics for regional operations; an antimeridian-crossing polygon must be split into appropriate MultiPolygon parts before submission. The API does not repair or infer intended dateline geometry.

Route lookup checks workspace ownership before distance evaluation. A missing or foreign route returns the same 404. All other queries explicitly constrain the workspace and do not disclose other tenants. Parameterized SQL prevents geometry/identifier interpolation. Candidate filtering uses spatial predicates and indexes; geometry coverage has a dedicated expression GiST index, and stop search has geography/time indexes from migration 004. Exact spheroidal distance ordering follows the radius prefilter rather than claiming approximate KNN ordering is exact.

The search is an explicit point-in-time query, not a continuous spatial subscription. Changing its inputs clears old hits, and late responses are ignored after edits or unmounting/sign-out. Route listing and saved-geofence selectors retain their existing listing limits (500 routes and 1,000 geofences). Richer team/status filters and snapshot-consistent cursor paging are future work.

Backend contracts appear in OpenAPI. Regression coverage uses real PostGIS/Redis; browser coverage sends GPS through authenticated ingestion and checks native query-result layers.
