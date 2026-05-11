# Step 3.6 — Staff Portal auth (PIN login)

**Goal:** PIN-based auth for staff at the shop tablet. Staff selects their name, enters last 4 digits of their phone. Issues a short-lived staff token (different scope from admin JWT).
**Phase:** 3
**Depends on:** 3.4, 1.6
**Status:** Pending

## Scope
**In-scope:**
- New auth endpoint: `POST /api/v1/staff-portal/auth/login` body=`{org_slug, user_id, pin}` returns `{staff_token, expires_at}`.
- Token is a JWT with `scope="staff"`, short TTL (4 hours), separate sign claim, includes `org_id`+`user_id`+`token_id`.
- New table `staff_sessions` (TenantScoped) for revocation.
- Endpoint `GET /api/v1/staff-portal/users` (returns minimal profiles for the login picker — full_name, role, avatar — public *within the org*; org context resolved by `org_slug` query param).
- New dependency `get_current_staff` for staff-only endpoints.
- Rate-limit PIN attempts (5 per minute per (org_id,user_id)).
- Audit log every PIN attempt (success and failure).

**Out of scope:**
- Frontend portal — 3.7.

## Files to touch
- `api/app/core/staff_portal/{__init__,router,service,models,schemas}.py` (created)
- `api/app/core/auth/dependencies.py` (modified — `get_current_staff`)
- `api/alembic/versions/0017_staff_sessions.py` (created)
- `api/app/main.py` (modified)

## Plan
1. Migration: `staff_sessions(token_id PK, org_id, user_id, created_at, expires_at, revoked_at)` + RLS + indexes.
2. Endpoint: validate org_slug → org. Validate user belongs to org and `staff_profile.employment_status='active'`. Compare last 4 digits of `users.phone` with PIN.
3. Issue staff token; insert `staff_sessions` row.
4. `get_current_staff` decodes, ensures `scope="staff"`, ensures session not revoked.
5. Public list endpoint for the picker exposes only safe fields.
6. Rate limit + audit hooks.

## Tests to add
- `tests/test_staff_portal_login.py` — happy path, wrong PIN, inactive user, rate limit.

## Verification checklist
**Backend:**
- `GET /staff-portal/users?org_slug=demo` → list (no PII beyond name/role/avatar).
- `POST /staff-portal/auth/login` correct PIN → 200 + token.
- wrong PIN 6× → 429.

## Self-check (10 rules)
- [ ] org_id + RLS on `staff_sessions`.
- [ ] Staff token scope distinct from admin token.

## Stop & report
Await "proceed" before Step 3.7.
