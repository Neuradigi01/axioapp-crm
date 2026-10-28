# Step 1.4 — Multi-tenancy primitives

**Goal:** Add the `RequestContext` middleware that resolves `org_id` (from JWT claim once auth lands; placeholder header for now), the `TenantScoped` mixin auto-applying `org_id` filters, a small repository helper, and a Postgres RLS policy on `organizations` plus a helper to apply RLS to any future table.
**Phase:** 1
**Depends on:** 1.3
**Status:** COMPLETED OK

## Scope
**In-scope:**

- `api/src/app/shared/context.py`: contextvar-based `RequestContext` (org_id, user_id, request_id).
- `api/src/app/shared/middleware.py`: `TenantContextMiddleware` that reads `X-Org-Id` header in dev (placeholder) — replaced in 1.6 by JWT-claim extraction.
- `api/src/app/shared/orm.py`: `TenantScoped` mixin (adds `org_id` Mapped column + index) and a session event listener that auto-injects `WHERE org_id = :ctx_org_id` on `Select` against TenantScoped models.
- `api/src/app/shared/repository.py`: generic async repository helper (`get`, `list`, `create`, `update`, `delete`) that uses the current session + tenant filter.
- `api/src/app/shared/rls.py`: helper `apply_rls(table_name, policy_name)` that emits `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` and `CREATE POLICY ... USING (org_id = current_setting('app.org_id')::uuid)`.
- Migration `0002_organizations_rls.py`: enables RLS on `organizations` itself (every query needs `SET LOCAL app.org_id`).
- DB session lifecycle hook: on session begin, `SET LOCAL app.org_id = :ctx_org_id` if present.

**Out of scope:**
- Real JWT extraction — 1.6 will replace the placeholder header with claim parsing.
- Adding RLS to any other table (none exist yet).

## Files to touch
- `api/src/app/shared/context.py` (created)
- `api/src/app/shared/middleware.py` (created)
- `api/src/app/shared/orm.py` (created)
- `api/src/app/shared/repository.py` (created)
- `api/src/app/shared/rls.py` (created)
- `api/src/app/shared/db.py` (modified — register session hook)
- `api/src/app/main.py` (modified — register middleware)
- `api/alembic/versions/0002_organizations_rls.py` (created)

## Plan
1. Implement `RequestContext` as a `contextvars.ContextVar` holding a small dataclass (org_id, user_id, request_id).
2. Implement middleware that opens a context for each request: read `X-Org-Id` (dev-only placeholder), generate a request id, set the contextvar, yield, then reset.
3. Implement `TenantScoped` mixin: `org_id: Mapped[UUID]` (FK to `organizations.id`, NOT NULL, indexed).
4. Register a SQLAlchemy `do_orm_execute` event that, on Select against any class with `TenantScoped`, appends a `where(org_id == ctx.org_id)` clause if not already present.
5. Implement `Repository[T]` generic with the standard CRUD methods, all relying on the current session and the tenant filter.
6. Implement `apply_rls(table_name)` helper for use in migrations.
7. Update `db.py` so that on each new session, if `ctx.org_id` is set, the session emits `SET LOCAL app.org_id = '<uuid>'` as the first statement (before any query).
8. Write migration `0002_organizations_rls.py` calling `apply_rls('organizations', 'org_isolation')`.
9. Register middleware in `main.py` after CORS.

## DB changes / migrations
- New migration `0002_organizations_rls`: enables RLS on `organizations`, creates policy `org_isolation` `USING (id = current_setting('app.org_id')::uuid)`.
- Down: drops policy + disables RLS.

## Tests to add
- `api/tests/test_tenant_filter.py` — creates two orgs A and B, opens a session under A's context, queries `Organization` → only A returned. Switches to B's context → only B returned. Without context → none returned (RLS denies).
- `api/tests/test_request_context.py` — middleware test asserting context populated and reset between requests.

## Verification checklist
**Backend:**
- run: `cd api && uv run alembic upgrade head` → `0002_organizations_rls` applied.
- run: `psql $DATABASE_URL -c "SELECT * FROM pg_policies WHERE tablename='organizations';"` → policy listed.
- run: `uv run pytest tests/test_tenant_filter.py -v` → green.
- hit: `curl http://localhost:8000/api/v1/health -H 'X-Org-Id: <demo-uuid>'` → still 200 (health is unscoped).

**Code review:**
- open `api/src/app/shared/orm.py` — note the `do_orm_execute` listener and how it appends the org_id filter only for `TenantScoped` models.
- open `api/src/app/shared/rls.py` — note the helper signature; will be reused on every future table migration.

## Self-check (10 rules)
- [ ] Rule 2 firmly in place: every future table will inherit `TenantScoped` and apply RLS.
- [ ] No TODOs.
- [ ] No `app/packs` import in core.

## Stop & report
Use the master-prompt stop template; await "proceed" before Step 1.5.
