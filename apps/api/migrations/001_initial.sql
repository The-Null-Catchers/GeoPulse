CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE users (
 id uuid PRIMARY KEY, email text NOT NULL UNIQUE, name text NOT NULL, password_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE organizations (
 id uuid PRIMARY KEY, name text NOT NULL, retention_days int NOT NULL DEFAULT 90 CHECK(retention_days BETWEEN 1 AND 3650),
 offline_seconds int NOT NULL DEFAULT 120 CHECK(offline_seconds BETWEEN 30 AND 86400),
 moving_speed real NOT NULL DEFAULT 1.5 CHECK(moving_speed > 0), stop_seconds int NOT NULL DEFAULT 180 CHECK(stop_seconds >= 30)
);
CREATE TABLE memberships (
 workspace_id uuid REFERENCES organizations ON DELETE CASCADE, user_id uuid REFERENCES users ON DELETE CASCADE,
 role text NOT NULL CHECK(role IN ('owner','admin','dispatcher','operator','viewer')),
 PRIMARY KEY(workspace_id,user_id)
);
CREATE TABLE refresh_sessions (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
 secret_hash text NOT NULL UNIQUE, family_id uuid NOT NULL, expires_at timestamptz NOT NULL,
 revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE teams (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES organizations ON DELETE CASCADE,
 name text NOT NULL, UNIQUE(workspace_id,id)
);
CREATE TABLE drivers (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES organizations ON DELETE CASCADE,
 name text NOT NULL, UNIQUE(workspace_id,id)
);
CREATE TABLE vehicles (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES organizations ON DELETE CASCADE,
 name text NOT NULL, registration text, UNIQUE(workspace_id,id)
);
CREATE TABLE devices (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES organizations ON DELETE CASCADE,
 name text NOT NULL, device_type text NOT NULL DEFAULT 'vehicle', active boolean NOT NULL DEFAULT true,
 token_hash text NOT NULL UNIQUE, team_id uuid, driver_id uuid, vehicle_id uuid,
 firmware_version text, metadata jsonb NOT NULL DEFAULT '{}', last_seen timestamptz,
 UNIQUE(workspace_id,id),
 FOREIGN KEY(workspace_id,team_id) REFERENCES teams(workspace_id,id),
 FOREIGN KEY(workspace_id,driver_id) REFERENCES drivers(workspace_id,id),
 FOREIGN KEY(workspace_id,vehicle_id) REFERENCES vehicles(workspace_id,id)
);
CREATE TABLE location_events (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL, device_id uuid NOT NULL, event_id uuid NOT NULL,
 recorded_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(),
 coordinates geography(Point,4326) NOT NULL, altitude real, speed real NOT NULL CHECK(speed>=0),
 bearing real NOT NULL CHECK(bearing>=0 AND bearing<360), accuracy real NOT NULL CHECK(accuracy>=0),
 battery_level real CHECK(battery_level>=0 AND battery_level<=100), source text NOT NULL,
 metadata jsonb NOT NULL DEFAULT '{}', UNIQUE(device_id,event_id),
 FOREIGN KEY(workspace_id,device_id) REFERENCES devices(workspace_id,id) ON DELETE CASCADE
);
CREATE INDEX location_device_time ON location_events(workspace_id,device_id,recorded_at,id);
CREATE INDEX location_time ON location_events USING brin(recorded_at);
CREATE INDEX location_geo ON location_events USING gist(coordinates);
CREATE TABLE device_status (
 device_id uuid PRIMARY KEY, workspace_id uuid NOT NULL, event_id uuid NOT NULL,
 recorded_at timestamptz NOT NULL, coordinates geography(Point,4326) NOT NULL,
 speed real NOT NULL, bearing real NOT NULL, battery_level real,
 state text NOT NULL DEFAULT 'unknown', stationary_since timestamptz,
 processed_at timestamptz, distance_today_m double precision NOT NULL DEFAULT 0, metric_date date,
 FOREIGN KEY(workspace_id,device_id) REFERENCES devices(workspace_id,id) ON DELETE CASCADE
);
CREATE INDEX status_geo ON device_status USING gist(coordinates);
CREATE TABLE geofences (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES organizations ON DELETE CASCADE,
 name text NOT NULL, geometry geometry(MultiPolygon,4326) NOT NULL,
 enabled boolean NOT NULL DEFAULT true, dwell_seconds int NOT NULL DEFAULT 300 CHECK(dwell_seconds >= 1),
 metadata jsonb NOT NULL DEFAULT '{}', UNIQUE(workspace_id,id)
);
CREATE INDEX fence_geo ON geofences USING gist(geometry);
CREATE TABLE geofence_state (
 device_id uuid NOT NULL, geofence_id uuid NOT NULL, workspace_id uuid NOT NULL,
 inside boolean NOT NULL, entered_at timestamptz, dwell_sent boolean NOT NULL DEFAULT false,
 PRIMARY KEY(device_id,geofence_id),
 FOREIGN KEY(workspace_id,device_id) REFERENCES devices(workspace_id,id) ON DELETE CASCADE,
 FOREIGN KEY(workspace_id,geofence_id) REFERENCES geofences(workspace_id,id) ON DELETE CASCADE
);
CREATE TABLE geofence_events (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL, device_id uuid NOT NULL, geofence_id uuid NOT NULL,
 event_type text NOT NULL CHECK(event_type IN ('enter','exit','dwell')), recorded_at timestamptz NOT NULL,
 coordinates geography(Point,4326) NOT NULL, location_id uuid REFERENCES location_events ON DELETE CASCADE,
 FOREIGN KEY(workspace_id,device_id) REFERENCES devices(workspace_id,id) ON DELETE CASCADE,
 FOREIGN KEY(workspace_id,geofence_id) REFERENCES geofences(workspace_id,id) ON DELETE CASCADE,
 UNIQUE(location_id,geofence_id,event_type)
);
CREATE TABLE routes (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES organizations ON DELETE CASCADE, name text NOT NULL,
 geometry geography(LineString,4326) NOT NULL, waypoints jsonb NOT NULL, distance_m double precision NOT NULL,
 duration_s double precision NOT NULL, provider text NOT NULL, UNIQUE(workspace_id,id)
);
CREATE INDEX route_geo ON routes USING gist(geometry);
CREATE TABLE route_assignments (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL, device_id uuid NOT NULL, route_id uuid NOT NULL,
 state text NOT NULL DEFAULT 'assigned', deviation_m real NOT NULL DEFAULT 150,
 deviation_seconds int NOT NULL DEFAULT 120, deviating_since timestamptz, eta_seconds real,
 FOREIGN KEY(workspace_id,device_id) REFERENCES devices(workspace_id,id) ON DELETE CASCADE,
 FOREIGN KEY(workspace_id,route_id) REFERENCES routes(workspace_id,id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX active_assignment ON route_assignments(device_id) WHERE state IN ('assigned','active');
CREATE TABLE trips (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL, device_id uuid NOT NULL,
 started_at timestamptz NOT NULL, ended_at timestamptz, distance_m double precision NOT NULL DEFAULT 0,
 moving_seconds double precision NOT NULL DEFAULT 0, idle_seconds double precision NOT NULL DEFAULT 0,
 max_speed real NOT NULL DEFAULT 0,
 FOREIGN KEY(workspace_id,device_id) REFERENCES devices(workspace_id,id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX active_trip ON trips(device_id) WHERE ended_at IS NULL;
CREATE TABLE stops (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL, device_id uuid NOT NULL,
 arrived_at timestamptz NOT NULL, departed_at timestamptz, coordinates geography(Point,4326) NOT NULL,
 FOREIGN KEY(workspace_id,device_id) REFERENCES devices(workspace_id,id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX active_stop ON stops(device_id) WHERE departed_at IS NULL;
CREATE TABLE alerts (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL, device_id uuid NOT NULL, kind text NOT NULL,
 severity text NOT NULL, state text NOT NULL DEFAULT 'open', created_at timestamptz NOT NULL DEFAULT now(),
 recorded_at timestamptz, acknowledged_at timestamptz, resolved_at timestamptz, assigned_user uuid REFERENCES users,
 notes text NOT NULL DEFAULT '',
 FOREIGN KEY(workspace_id,device_id) REFERENCES devices(workspace_id,id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX open_alert ON alerts(device_id,kind) WHERE state IN ('open','acknowledged');
CREATE TABLE alert_rules (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES organizations ON DELETE CASCADE,
 kind text NOT NULL, enabled boolean NOT NULL DEFAULT true, threshold real NOT NULL, UNIQUE(workspace_id,kind)
);
CREATE TABLE saved_views (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL, user_id uuid NOT NULL, name text NOT NULL, configuration jsonb NOT NULL,
 FOREIGN KEY(workspace_id,user_id) REFERENCES memberships(workspace_id,user_id) ON DELETE CASCADE
);
CREATE TABLE audit_logs (
 id uuid PRIMARY KEY, workspace_id uuid REFERENCES organizations ON DELETE CASCADE, user_id uuid REFERENCES users,
 action text NOT NULL, resource_id uuid, created_at timestamptz NOT NULL DEFAULT now(), metadata jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE api_keys (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES organizations ON DELETE CASCADE, name text NOT NULL,
 secret_hash text NOT NULL UNIQUE, scopes text[] NOT NULL, expires_at timestamptz NOT NULL,
 revoked_at timestamptz, last_used_at timestamptz
);
CREATE TABLE outbox (
 id bigserial PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES organizations ON DELETE CASCADE,
 topic text NOT NULL, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 processed_at timestamptz, published_at timestamptz
);
CREATE INDEX pending_outbox ON outbox(id) WHERE published_at IS NULL;
CREATE TABLE location_snapshots (
 id bigserial PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES organizations ON DELETE CASCADE,
 created_at timestamptz NOT NULL DEFAULT now(), payload jsonb NOT NULL
);
CREATE TABLE historical_metrics (
 workspace_id uuid NOT NULL REFERENCES organizations ON DELETE CASCADE, device_id uuid NOT NULL,
 date date NOT NULL, distance_m double precision NOT NULL, PRIMARY KEY(workspace_id,device_id,date),
 FOREIGN KEY(workspace_id,device_id) REFERENCES devices(workspace_id,id) ON DELETE CASCADE
);
CREATE TABLE device_commands (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL, device_id uuid NOT NULL, command text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), state text NOT NULL DEFAULT 'pending', payload jsonb NOT NULL DEFAULT '{}',
 FOREIGN KEY(workspace_id,device_id) REFERENCES devices(workspace_id,id) ON DELETE CASCADE
);
CREATE TABLE invitations (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES organizations ON DELETE CASCADE,
 email text NOT NULL, role text NOT NULL CHECK(role IN ('admin','dispatcher','operator','viewer')),
 secret_hash text NOT NULL UNIQUE, expires_at timestamptz NOT NULL, accepted_at timestamptz
);
