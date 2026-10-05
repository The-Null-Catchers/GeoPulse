# Security and privacy

## Implemented controls

Passwords use Argon2. User access JWTs are short-lived and validate signature, issuer, audience, required fields and token type. Refresh credentials are random, stored as SHA-256 digests, rotated under row locks and grouped into families. Reuse revokes the whole family in a committed transaction before a 401 response. Logout revokes the family. Browser refresh cookie is HttpOnly and SameSite Strict; secure mode must be true outside localhost.

Device/API/invitation secrets are cryptographically random and hashed at rest. Device and API secrets are returned only at creation/rotation. Device tokens can ingest only that device's data and cannot read operator APIs. Scoped expiring API keys are checked against their workspace, method-derived read/write scope and revocation. Last use is recorded.

Workspace authorization is enforced on every operational selector. Roles: owner, admin, dispatcher, operator and viewer; devices use a distinct credential type. Composite tenant foreign keys prevent cross-workspace references. Owners/admins manage sensitive settings and credentials; dispatchers provision/route/fence; operators acknowledge alerts; viewers read. One-time WebSocket tickets enforce origin, membership and device scope.

Redis-backed fixed-window rate limits protect registration, login, users, API keys and each device. Inputs forbid extra fields, reject nonfinite numeric values and bound batches, time ranges and geometry sizes. SQL values are parameterized. No committed production credentials exist; `.env` is ignored and the environment generator refuses overwrite.

Caddy exposes only intended HTTP routes. API sets no-store, request IDs and response headers; web includes frame denial, CSP and restrictive permissions policy. PostGIS/Redis have no host-published ports. Containers run application processes as nonroot. Request logs omit request bodies, authorization headers and query strings, including realtime tickets.

## Privacy controls

Mobile explains what will be collected, asks for consent, requests OS permission and provides an explicit tracking state/stop control. This milestone collects only while visible; app pause stops collection. Offline UUIDs and timestamps persist in SQLite until acknowledgement or explicit deletion. Tokens are in platform secure storage; location queue encryption is not yet implemented.

Workspace retention is configurable. Worker prunes old GPS and derived trip/stop/alert/metric/snapshot records; disabling a device rejects new GPS/heartbeats. Admin history erasure removes raw events, current position, trips, stops, metrics, fence state, related events, alerts and matching pending/published outbox payloads, removes associated webhook delivery payloads/attempts, then emits an erasure notification. Backups may still contain old data until their documented retention expires.

## Release blockers and boundaries

This source is not a completed security review. Password recovery/verification email, account/session administration, stricter signup controls, CSP nonces, distributed WebSocket quotas/backpressure, poisoned-event recovery, offline database encryption, completed retention UI and ongoing dependency/secret scans remain work. Webhooks enforce an administrator-configured exact host allowlist, HTTPS on port 443, public-only DNS results pinned at connection time, no redirects/proxy inheritance, bounded timeouts and encrypted signing credentials. Delivery and attempts persist; signatures bind timestamp, stable delivery ID and exact body. See WEBHOOKS.md. A request already in flight cannot be recalled after disabling a hook or erasing history.

The Next.js CSP permits inline script/style for current framework hydration. The demo uses external OpenStreetMap tiles; configure a self-hosted/licensed tile URL and attribution for private/production deployments. Web CSP derives its permitted tile origin from the build configuration. The browser sends only the origin as its cross-origin Referer; API responses retain no-referrer. Tile requests disclose viewport activity to those providers; do not describe the default demo as fully offline or fully private.

Tests cover foreign-workspace access, composite-FK association rejection, viewer write denial, authenticated ingestion, scoped-key revocation and refresh reuse. Independent ZAP/Burp/penetration testing, sustained abuse/DoS tests, mobile device testing and browser security checks have not been completed. No claim of production readiness is implied by passing these regression tests.
