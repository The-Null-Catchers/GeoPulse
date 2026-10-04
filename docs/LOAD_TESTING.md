# Load testing and scale

## Reproduce

Start the full stack and install `apps/api/requirements-dev.txt`. Run:

```sh
python scripts/load-test.py --devices 100 --clients 3 --ticks 10 --interval 2 \
  --output docs/load-test-result.json
```

REST defaults to localhost:8000, WebSocket to localhost:8000 and origin to localhost:3000. If Compose uses localhost as its sole origin, pass `--origin http://localhost`. The script provisions a unique workspace and real device credentials, opens multiple authenticated sockets, sends unique GPS events via HTTP and asserts all accepted events reached every subscriber. Each HTTP acceptance and each device-to-WebSocket elapsed duration is measured on the same monotonic clock. It gives the worker a bounded 30s drain deadline and fails missing delivery counts.

The simulator additionally supports batch payloads and 1,000 devices, but 1,000-device results are **not verified**. Provisioning/rate limits must be respected for larger runs; the current per-user cap is 600 requests/minute. Use deliberate provisioning windows or a staging-only limit configuration before a large soak test. Do not disable production limits to make a benchmark look better.

## Current evidence

Read the checked-in JSON for exact latest measurements. The initial verified scenario is 100 devices, 10 ticks at 2s, 1,000 accepted events and 3,000 deliveries across 3 clients, with zero HTTP errors. These are short local measurements with one ordered worker, not sustained peak throughput. PostgreSQL 16.15/PostGIS 3.4.2 and Redis 7.0.15 were run as disposable test services; Compose images were not run locally. The namespace's single UID required a test-only identity adapter to launch PostgreSQL; it is outside project code and must never be used in deployment.

HTTP timing measures request acceptance including client concurrency; it does not equal pure insert time. WebSocket timing measures from producer dispatch until a subscriber sees the processed live location. A warm radius query is measured separately, including client fetch. Optional CPU/RSS evidence from the local harness includes startup/provisioning/client workload and is labeled by scope; it is not per-container utilization or total simultaneous fleet-service RSS. A plain script run reports unavailable system metrics as null rather than inventing values.

## Scaling strategy

Location writes currently use per-point SQL inside one transaction. Next improvements: parameterized multi-row inserts/COPY, aggregated outbox processing, cached enabled fences with indexed candidate filtering, reduced per-point read/write amplification and explicit device-sharded consumers. Advisory-lock serialization is a correctness-oriented MVP bottleneck.

Location table is currently unpartitioned. Plan monthly time partitions after measuring retention/write volume. A global `(device_id,event_id)` deduplication ledger is required if location partition keys prevent that unique constraint across partitions; do not silently weaken idempotency when partitioning. Retention should drop complete expired partitions and prune only boundary partitions.

History uses device/time pagination. Heatmaps bin server-side with bounded result counts. Snapshot/live device list caps at 1,000, UI replay at 5,000 points; true fleet-wide aggregates and streamed/vector-tile history are needed beyond that boundary. Redis pub/sub is ephemeral; durable client delivery could use a scoped stream/cursor with retention and tenant-safe resumption.

Remaining tests: hours-long 100/1,000-device soak, batched retry/offline bursts, large historical dataset/query plans, many WebSocket subscribers/slow readers, RSS/CPU per container, Redis outage/recovery, worker kill/restart and database failover. Current measurements must not be used to promise those scenarios.
