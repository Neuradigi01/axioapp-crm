# Step 2.6 — Activities timeline: backend

**Goal:** `activities` table + service. Endpoints to log and list activities for any entity. Internal `activities.log(...)` helper for other modules.
**Phase:** 2
**Depends on:** 2.4
**Status:** Pending

## Scope
**In-scope:**
- Model `Activity` (TenantScoped): id, org_id, entity_type (contact/lead/walk_in/...), entity_id, type (call/note/email/whatsapp/status_change/task), payload JSONB, user_id (nullable for system events), created_at.
- Migration with index `(org_id, entity_type, entity_id, created_at desc)`.
- Schemas + service:
  - `log(entity_type, entity_id, type, payload, user_id=...)` — internal helper.
  - `list(entity_type, entity_id, limit=...)` — paginated.
- Endpoints: `GET /api/v1/activities?entity_type=...&entity_id=...`, `POST /api/v1/activities` (manual notes only — `type=note`).
- Permission `activities.read`.

**Out of scope:**
- Frontend — 2.7.
- Wiring to other modules (added per module).

## Files to touch
- `api/app/core/activities/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0008_activities.py` (created)
- `api/app/main.py` (modified)

## Plan
1. Model + migration with proper index.
2. Service `log()` is async; never raises into caller (try/except + structured log).
3. Service `list()` with pagination; latest first.
4. Router exposes manual note creation. Validate payload shape (`{text: str}` for notes).
5. Permission registered; admin role gets it via seed.

## Tests to add
- `tests/test_activities_log.py` — log + list cycle.
- `tests/test_activities_rls.py` — other org's activities invisible.

## Verification checklist
**Backend:**
- hit: `POST /activities` body=`{entity_type:"contact",entity_id:"<uuid>",type:"note",payload:{text:"hello"}}` → 201.
- hit: `GET /activities?entity_type=contact&entity_id=<uuid>` → list with the note.

## Self-check (10 rules)
- [ ] org_id + RLS.
- [ ] Service helper is reusable from any future module without a circular import.

## Stop & report
Await "proceed" before Step 2.7.
