-- Polygon predicates use geometry; geography GiST alone cannot index this cast.
CREATE INDEX status_geometry_geo ON device_status USING gist ((coordinates::geometry));
CREATE INDEX stop_geo ON stops USING gist (coordinates);
CREATE INDEX stop_workspace_arrival ON stops (workspace_id, arrived_at);
