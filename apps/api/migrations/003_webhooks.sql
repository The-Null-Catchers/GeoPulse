CREATE TABLE webhooks (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES organizations ON DELETE CASCADE,
 name text NOT NULL, url text NOT NULL, event_types text[] NOT NULL,
 encrypted_secret text NOT NULL, enabled boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(workspace_id,id)
);
CREATE TABLE webhook_deliveries (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL, webhook_id uuid NOT NULL,
 event_id bigint NOT NULL, device_id uuid, payload jsonb NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','sending','retry','delivered','failed','cancelled')),
 attempts int NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL DEFAULT now(),
 lease_token uuid, leased_until timestamptz, last_http_status int, last_error text,
 created_at timestamptz NOT NULL DEFAULT now(), delivered_at timestamptz,
 UNIQUE(webhook_id,event_id),
 FOREIGN KEY(workspace_id,webhook_id) REFERENCES webhooks(workspace_id,id) ON DELETE CASCADE,
 FOREIGN KEY(workspace_id,device_id) REFERENCES devices(workspace_id,id) ON DELETE CASCADE
);
CREATE INDEX webhook_due ON webhook_deliveries(next_attempt_at,id) WHERE state IN ('pending','sending','retry');
CREATE TABLE webhook_attempts (
 id bigserial PRIMARY KEY, delivery_id uuid NOT NULL REFERENCES webhook_deliveries ON DELETE CASCADE,
 attempt int NOT NULL, started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
 http_status int, error text, duration_ms real, UNIQUE(delivery_id,attempt)
);
