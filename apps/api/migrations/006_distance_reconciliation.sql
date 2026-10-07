CREATE TABLE distance_reconciliation_jobs (
 workspace_id uuid NOT NULL,
 device_id uuid NOT NULL,
 date date NOT NULL,
 requested_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (workspace_id,device_id,date),
 FOREIGN KEY (workspace_id,device_id) REFERENCES devices(workspace_id,id) ON DELETE CASCADE
);
CREATE INDEX distance_jobs_requested ON distance_reconciliation_jobs(requested_at);
CREATE INDEX unprocessed_device_locations ON outbox(workspace_id,(payload->>'device_id'))
 WHERE topic='location.received' AND processed_at IS NULL;
