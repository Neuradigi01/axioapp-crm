# Step 1.5 — Users, Roles, Permissions

**Goal:** Migrate the existing user/role schema into the new layered layout under `app/core/users/`, `app/core/permissions/`, all `org_id`-scoped, RLS-enabled. Seed: one admin role, one user with hashed password, one basic permission set.
**Phase:** 1
**Depends on:** 1.4
**Status:** Pending

## Scope
**In-scope:**
- New layered models under `app/core/users/` and `app/core/permissions/`:
  - `users` (id, org_id, email, password_hash, full_name, phone, role_id, is_active, created_at, updated_at)
  - `roles` (id, org_id, name, is_system, created_at)
  - `permissions` (id, key, description, module) — **global**, NOT tenant-scoped (the registry is shared).
  - `role_permissions` (role_id, permission_id).
- Re-house the existing user model code (from `api/src/models/user.py` + `data_access/user_da.py` + `services/auth/`) into the new vertical layout. Source files become reference; new files are canonical.
- Migration `0003_users_roles_permissions.py` creating the four tables + RLS on tenant-scoped ones.
- Seed script `seed_admin_user.py`: one admin role, one user (`admin@demo.local`, password `Admin@123` hashed), permissions: `users.read`, `users.write`, `roles.read`, `roles.write`. Idempotent.
- `GET /api/v1/users/me` returning the current user (placeholder: reads `X-Org-Id` + `X-User-Id` headers in dev; replaced by JWT in 1.6).
- Output raw INSERT SQL for the seed user/role/permissions.

**Out of scope:**
- JWT issuance / login endpoint — 1.6.
- Audit logs — 1.7.
- Deleting the old `api/src/...` paths (kept as reference until 1.6 finalizes auth migration).

## Files to touch
- `api/src/app/core/users/__init__.py` (created)
- `api/src/app/core/users/models.py` (created — `User`)
- `api/src/app/core/users/schemas.py` (created — Pydantic v2)
- `api/src/app/core/users/service.py` (created — read/list, password hashing wrapper)
- `api/src/app/core/users/router.py` (created — `/users/me`, `/users` admin list)
- `api/src/app/core/permissions/__init__.py` (created)
- `api/src/app/core/permissions/models.py` (created — `Role`, `Permission`, `RolePermission`)
- `api/src/app/core/permissions/schemas.py` (created)
- `api/src/app/core/permissions/service.py` (created — registers permissions from modules)
- `api/src/app/shared/security/password.py` (created — bcrypt wrapper, copied/refactored from existing `api/src/core/security/password.py`)
- `api/alembic/versions/0003_users_roles_permissions.py` (created)
- `api/src/app/scripts/seed_admin_user.py` (created)
- `api/src/app/main.py` (modified — register `users` router)

## Plan
1. Define models in the new layered layout. `User` and `Role` inherit `TenantScoped`; `Permission` and `RolePermission` are global.
2. Define Pydantic v2 schemas: `UserOut`, `UserMe`, `RoleOut`, `PermissionOut`. No request schemas yet (CRUD comes in admin UI later).
3. Implement `app/shared/security/password.py` (bcrypt hash + verify) — copy logic from existing `api/src/core/security/password.py`, port to module location.
4. Service layer: `users.get_by_id`, `users.get_by_email`, `permissions.list_for_role`, `roles.get_by_id`. Repository pattern per 1.4.
5. Router: `GET /api/v1/users/me` returns the user from `RequestContext` (dev: `X-User-Id` header → 1.6 replaces with JWT).
6. Migration: create the four tables, FKs, indexes, RLS on `users` + `roles`, no RLS on `permissions`/`role_permissions`.
7. Seed: insert `admin` role (org-scoped, `is_system=true`), four permissions (global), three role_permissions, one user with bcrypt-hashed password. Use UPSERT.
8. Print INSERT SQL for the user/role/permissions in the step report.

## DB changes / migrations
- Migration `0003_users_roles_permissions`:
  - `roles(id uuid PK, org_id uuid FK→organizations, name text, is_system bool, created_at timestamptz)` + RLS.
  - `users(id uuid PK, org_id uuid FK→organizations, email citext UNIQUE per org, password_hash text, full_name text, phone text, role_id uuid FK→roles, is_active bool, created_at, updated_at)` + RLS + unique index on `(org_id, lower(email))`.
  - `permissions(id uuid PK, key text UNIQUE, description text, module text)`.
  - `role_permissions(role_id uuid FK→roles, permission_id uuid FK→permissions, PK(role_id,permission_id))`.

## Tests to add
- `api/tests/test_user_create.py` — create org A user, fetch via `/users/me` with A context, succeeds. With B context, returns 404.
- `api/tests/test_password_hash.py` — hash + verify round-trip; wrong password rejected.

## Verification checklist
**Backend:**
- run: `uv run alembic upgrade head` → 0003 applied.
- run: `uv run python -m src.app.scripts.seed_admin_user` → prints inserted user id.
- run: `psql $DATABASE_URL -c "\dt" | findstr users` → users, roles, permissions, role_permissions.
- hit: `curl localhost:8000/api/v1/users/me -H 'X-Org-Id: <demo-uuid>' -H 'X-User-Id: <admin-uuid>'` → 200 with user JSON.
- run: `uv run pytest -q` → green.

**Code review:**
- open `api/src/app/core/users/models.py` — note `TenantScoped` mixin used.
- open `api/src/app/core/permissions/models.py` — note Permission is global, not TenantScoped.

## Self-check (10 rules)
- [ ] `org_id` on `users` and `roles`; RLS enabled.
- [ ] Step touched ≤ ~13 files (allow up to ~13 here given migration complexity; if > 13 split).
- [ ] No imports from `app/packs` in `app/core/`.
- [ ] No TODOs.

## Stop & report
Use the master-prompt stop template; **include INSERT SQL** for the seeded user/role/permissions; await "proceed" before Step 1.6.
