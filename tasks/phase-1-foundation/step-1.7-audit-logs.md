# Step 1.7 — Audit logs

**Goal:** Add the `audit_logs` table, a small `audit.log(action, entity, before, after)` service, hook it into the auth flow (login success/failure), and expose an admin endpoint to list recent audit entries.
**Phase:** 1
**Depends on:** 1.5, 1.6
**Status:** Pending

## Scope
**In-scope:**
- `audit_logs` table: `id`, `org_id`, `user_id` (nullable for failed logins), `action`, `entity_type`, `entity_id`, `before` JSONB, `after` JSONB, `ip`, `ua`, `created_at`. `TenantScoped`, RLS.
- `app/core/audit/service.py`: `log(action, entity_type=None, entity_id=None, before=None, after=None)` — reads `RequestContext` for user/ip/ua/org.
- Hook `audit.log("auth.login.success" / "auth.login.failure")` in the login service.
- `GET /api/v1/audit-logs` endpoint (paginated, filter by `entity_type`, `action`, date range), gated by `audit.read` permission.
- Migration `0005_audit_logs.py`.

**Out of scope:**
- Wiring `audit.log` into other modules (each module hooks it as it's built).
- An admin UI for audit logs (later phase).

## Files to touch
- `api/app/core/audit/__init__.py` (created)
- `api/app/core/audit/models.py` (created)
- `api/app/core/audit/schemas.py` (created)
- `api/app/core/audit/service.py` (created)
- `api/app/core/audit/router.py` (created)
- `api/app/core/auth/service.py` (modified — `audit.log("auth.login.success"/"auth.login.failure")`)
- `api/app/core/permissions/service.py` (modified — register `audit.read`)
- `api/alembic/versions/0005_audit_logs.py` (created)
- `api/app/main.py` (modified — register router)

## Plan
1. Define `AuditLog` model with `TenantScoped`. Use `JSONB` for before/after.
2. Define schemas: `AuditLogOut`, list filter query.
3. Implement service: `log(...)` builds an entry from RequestContext and persists in a separate transaction (best-effort — never break the parent flow).
4. Migration: create table + indexes (`org_id`, `created_at desc`, `action`, `entity_type`, `entity_id`).
5. Hook in `auth.service.login`: log success/failure with email + reason.
6. Add `audit.read` permission to the permissions registry; seed it onto the admin role.
7. Endpoint `GET /api/v1/audit-logs?action=&entity_type=&from=&to=&page=&size=` returning paginated rows.
8. Failures in `audit.log` must NOT break the parent request — wrap in try/except + log to stderr.

## DB changes / migrations
- `0005_audit_logs`: table + RLS + indexes.

## Tests to add
- `tests/test_audit_login.py` — successful login writes an `auth.login.success` row; failed login writes `auth.login.failure` with `user_id NULL`.
- `tests/test_audit_list.py` — list endpoint paginates, filters by action, respects RLS (other org's audit invisible).

## Verification checklist
**Backend:**
- run: `uv run alembic upgrade head` → 0005 applied.
- hit: login → check `SELECT * FROM audit_logs` shows row.
- hit: bad login → row with `user_id IS NULL`, `action='auth.login.failure'`.
- hit: `GET /api/v1/audit-logs` → list of recent logs.
- run: `uv run pytest -q` → green.

**Code review:**
- open `api/app/core/audit/service.py` — note try/except guard; never breaks parent flow.

## Self-check (10 rules)
- [ ] org_id + RLS on audit_logs.
- [ ] `audit.read` registered, not hardcoded.
- [ ] No TODOs.

## Stop & report
Use the master-prompt stop template; await "proceed" before Step 1.8.
