# Realtime delivery

## Persistence before publication

GPS requests commit to `location_events` and `outbox` in one transaction. Worker reads the oldest pending row, computes spatial effects and commits its processed payload. Only then does it publish on `workspace:<uuid>`. A subsequent transaction sets `published_at`. If Redis fails, the event remains publishable. If a worker crashes after publication and before acknowledgement, the same ID can be published twice.

Database effects are transactionally idempotent because the processed marker and effects commit together. Location insertion separately deduplicates producer UUIDs. Worker errors roll back effects and retry rather than returning fake success. A poison event can block the ordered MVP worker; dead-letter tooling is a remaining release requirement.

## WebSocket authorization

The browser first requests `/api/v1/realtime/ticket` using its authorized access session and workspace header. A random ticket lasts 30s and is consumed exactly once by Redis GETDEL. WebSocket upgrade checks origin, current membership and optional device ownership. Ticket is not a reusable JWT. Membership is rechecked during the heartbeat loop. API keys cannot obtain user realtime tickets in this version.

Heartbeats are sent every ~20s. Clients deduplicate outbox IDs, reconnect with backoff, obtain a fresh ticket, and refetch current device state on connection. Dashboard also resynchronizes every 30s to recover missed pub/sub events. The browser should not rely on Redis pub/sub to preserve messages while disconnected.

## Guarantees and limits

- Server-side effects and at-least-once publication survive Redis outage/restart after ingestion.
- Connected same-workspace subscribers receive live updates; tests verify delivery.
- Reconnecting browsers recover the latest map state via REST, not every intermediate message.
- No durable per-client replay/acknowledgement cursor exists yet.
- One worker is supported for ordered processing. Distributed sharding remains a future step.
- Subscription buffers/backpressure limits and WebSocket load abuse controls need additional hardening.
- Redis WebSocket connection metric is approximate and can drift after abrupt process loss.

See `scripts/load-test.py` for a 100-device/multiple-subscriber validation scenario and `docs/load-test-result.json` for measured evidence.

## Durable webhook delivery

Spatial processing also inserts subscribed webhook delivery rows in the same transaction as its processed outbox payload. Unique webhook/event IDs prevent duplicate scheduling. The separate webhook worker leases jobs with SKIP LOCKED, performs signed HTTPS requests outside database transactions and persists each attempt. Redis outages do not erase delivery jobs. See [WEBHOOKS.md](WEBHOOKS.md).
