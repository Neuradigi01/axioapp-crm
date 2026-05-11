# Step 2.15 — Notifications: backend

**Goal:** `notifications` table + service. WebSocket endpoint for real-time delivery. Per-user notification preferences.
**Phase:** 2
**Depends on:** 1.6
**Status:** Pending

## Scope
**In-scope:**
- Models:
  - `Notification` (TenantScoped): id, org_id, user_id, type (string), title, body, payload JSONB, read_at, created_at.
  - `NotificationPreference` (TenantScoped): user_id, type, channel (in_app/email/push), enabled.
- Migration + RLS + indexes (`user_id, read_at`).
- Service: `notify(user_id, type, title, body, payload=None)` — persists + pushes to active WebSocket connections for that user.
- Endpoints:
  - `GET /api/v1/notifications?unread=true&limit=...`
  - `PATCH /api/v1/notifications/{id}/read`
  - `POST /api/v1/notifications/read-all`
  - `GET /api/v1/notification-preferences`, `PATCH /api/v1/notification-preferences/{type}`
  - `WS /api/v1/notifications/stream` — JWT auth on connect, sends new notifications JSON-encoded.
- Connection manager (in-process dict by user_id → set of WebSockets) for now. Multi-process scaling deferred to Phase 6.

**Out of scope:**
- Email/SMS push delivery — later.
- Frontend — 2.16.

## Files to touch
- `api/src/app/core/notifications/{__init__,models,schemas,service,router,ws,manager,module}.py` (created)
- `api/alembic/versions/0013_notifications.py` (created)
- `api/src/app/main.py` (modified — register router + WS)

## Plan
1. Models + migration.
2. Connection manager: `add(user_id, ws)`, `remove(user_id, ws)`, `broadcast(user_id, msg)`.
3. WS endpoint: handshake validates JWT; on success registers connection; on close removes.
4. `notify()` service: persists row, then `manager.broadcast(user_id, notification_json)`.
5. REST endpoints for list / mark-read / preferences.

## Tests to add
- `tests/test_notifications_crud.py`
- `tests/test_notifications_ws.py` — connect, trigger notify, receive message.

## Verification checklist
**Backend:**
- Connect via `wscat -c "ws://localhost:8000/api/v1/notifications/stream?token=<jwt>"` → idle.
- In another terminal: `notify` service call (Python REPL or POST to a test endpoint) → message arrives in wscat.
- `GET /notifications` → list.

## Self-check (10 rules)
- [ ] org_id + RLS.
- [ ] Service helper reusable from any module.

## Stop & report
Await "proceed" before Step 2.16.
