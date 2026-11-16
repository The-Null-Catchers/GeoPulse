CREATE INDEX location_replay_cursor ON location_events (workspace_id, device_id, recorded_at, event_id);
CREATE INDEX geofence_replay_time ON geofence_events (workspace_id, device_id, recorded_at, id);
CREATE INDEX stop_replay_arrival ON stops (workspace_id, device_id, arrived_at);
CREATE INDEX stop_replay_departure ON stops (workspace_id, device_id, departed_at);
CREATE INDEX alert_replay_time ON alerts (workspace_id, device_id, (coalesce(recorded_at, created_at)));
