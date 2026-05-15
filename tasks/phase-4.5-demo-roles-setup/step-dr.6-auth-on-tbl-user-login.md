# Step DR.6 — Move FurnitureCRM auth onto `tbl_user_login`

**Goal:** Make `tbl_user_login` the single source of truth for FurnitureCRM logins. Add the multi-tenant + RBAC columns it's missing, migrate the 4 demo users out of `users` and into `tbl_user_login`, and rewrite the auth chain to read from the new home. Keep all existing `tbl_user_login` columns intact so the legacy `/accounts/admin-login` flow keeps working. **Keep the `users` table physically intact as a 2-week safety net** — auth code stops reading it but the rows stay.
**Phase:** 4.5 — Demo Roles Setup (side task)
**Depends on:** DR.1, DR.2, DR.3, DR.4, DR.5
**Status:** Done (smoked 2026-05-15; `users` table parked for soak — revisit on or after 2026-05-29)

---

## Why we're doing this

The user wants ONE login table the team can inspect, instead of:
- `tbl_user_login` (legacy template) — 1 row, drives `/accounts/admin-login` → `/admin/...`
- `users` (layered FurnitureCRM) — 5 rows, drives `/accounts/login` → `/user/...`

After DR.6: `tbl_user_login` holds **all 5 rows** (1 legacy + 4 demo). FurnitureCRM auth reads from it. Legacy admin login keeps working unchanged. `users` table stays orphaned until we're confident enough to drop it later.

---

## The "carefully" discipline

This touches the central auth path. Mistakes lock everyone out. So we break DR.6 into **6 micro-steps** with explicit smoke checks + an explicit rollback plan after each. Pause at the end of each micro-step, smoke, and only proceed when green. Anything red → revert that micro-step and stop.

| Sub-step | What it does | Reversible? |
|---|---|---|
| DR.6.1 | Migration: add columns to `tbl_user_login` (all nullable) | Yes — `alembic downgrade -1` |
| DR.6.2 | Migration: copy `users` rows into `tbl_user_login`, populate `legacy_uuid` bridge | Yes — `alembic downgrade -1` |
| DR.6.3 | Repoint `User` model's `__tablename__` to `tbl_user_login`; keep column aliases | Yes — flip one string back |
| DR.6.4 | Update auth login lookup + JWT issuance to read from `tbl_user_login` | Yes — revert one file 
| DR.6.5 | Update `/users/me`, `/_dev/demo-logins`, both seed scripts | Yes — revert each file |
| DR.6.6 | End-to-end smoke: all 5 logins work; rebuild Angular; mark `users` table as "soak" (keep, don't drop) | n/a — verification only |

If anything fails on the way, we stop at that micro-step. The container can be reverted by `git checkout` of the touched files + `alembic downgrade` of the touched revisions.

---

## DR.6.1 — Schema only: add columns to `tbl_user_login`

**Migration:** `api/alembic/versions/0031_tbl_user_login_for_crm.py`

```sql
ALTER TABLE tbl_user_login
  ADD COLUMN email           CITEXT,
  ADD COLUMN org_id          UUID REFERENCES organizations(id) ON DELETE RESTRICT,
  ADD COLUMN role_id         UUID REFERENCES roles(id) ON DELETE RESTRICT,
  ADD COLUMN full_name       VARCHAR(255),
  ADD COLUMN phone           VARCHAR(32),
  ADD COLUMN is_demo         BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN legacy_uuid     UUID,
  ADD COLUMN created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN updated_at      TIMESTAMPTZ NOT NULL DEFAULT now();

-- Partial unique index so (org_id, email) is unique only when both are set.
-- The legacy USR29684795 row has neither — exempted by the WHERE clause.
CREATE UNIQUE INDEX uq_tbl_user_login_org_email
  ON tbl_user_login (org_id, email)
  WHERE email IS NOT NULL AND org_id IS NOT NULL;

-- Bridge for the existing demo_credentials.user_id (uuid) FK.
CREATE UNIQUE INDEX uq_tbl_user_login_legacy_uuid
  ON tbl_user_login (legacy_uuid)
  WHERE legacy_uuid IS NOT NULL;
```

**Why `legacy_uuid`:** `demo_credentials.user_id` is a UUID FK that currently points at `users.id`. After DR.6.2 we want it to point at `tbl_user_login` rows. But `tbl_user_login.id` is `bigint`. Adding `legacy_uuid` lets us preserve the existing UUID values from `users` — and the dev-router JOIN becomes `demo_credentials.user_id = tbl_user_login.legacy_uuid` (one line change).

**Smoke after DR.6.1:**
```
.\docker-helper.cmd upgrade
# verify the 9 new columns exist on tbl_user_login
# verify the legacy USR29684795 row still validates (no NOT NULL violations)
```
**Rollback:** `.\docker-helper.cmd downgrade 1`

---

## DR.6.2 — Data migration: copy `users` → `tbl_user_login`

**Migration:** `api/alembic/versions/0032_migrate_users_to_tbl_user_login.py`

```sql
INSERT INTO tbl_user_login (
  user_id, password, email, org_id, role_id, full_name, phone,
  is_demo, is_active, two_factor_enabled, legacy_uuid,
  created_at, updated_at
)
SELECT
  'usr_' || REPLACE(u.id::text, '-', '') AS user_id,
  u.password_hash,
  u.email,
  u.org_id,
  u.role_id,
  u.full_name,
  u.phone,
  u.is_demo,
  u.is_active,
  FALSE,
  u.id,                  -- preserve the original UUID as legacy_uuid
  u.created_at,
  u.updated_at
FROM users u
WHERE NOT EXISTS (
  SELECT 1 FROM tbl_user_login t WHERE t.legacy_uuid = u.id
);
```

**Smoke after DR.6.2:**
```sql
SELECT COUNT(*) FROM tbl_user_login;
-- expect 5 (1 legacy + 4 demo)

SELECT user_id, email, org_id, role_id, is_demo FROM tbl_user_login;
-- expect: 1 legacy row (no email, no org), 4 demo rows (email + org + role populated)

SELECT t.email, dc.label
FROM demo_credentials dc
JOIN tbl_user_login t ON t.legacy_uuid = dc.user_id;
-- expect 4 rows matching by legacy_uuid
```

**Rollback:** `.\docker-helper.cmd downgrade 1` — removes the 4 new rows; legacy `USR29684795` untouched.

---

## DR.6.3 — Repoint the `User` SQLAlchemy model

Update `api/src/app/core/users/models.py`:
- Change `__tablename__ = "users"` → `__tablename__ = "tbl_user_login"`
- Change `id: Mapped[uuid.UUID]` → `id: Mapped[int]` (BigInteger primary key, autoincrement)
- Add `legacy_uuid: Mapped[uuid.UUID | None]`
- Add a `password: Mapped[str]` column matching the legacy column name. To keep existing `user.password_hash` accesses working, add a Python-side `@property` aliasing `password_hash` → `password`.
- Add the new Mapped columns: `email`, `org_id`, `role_id`, `full_name`, `phone`, `is_demo`, `created_at`, `updated_at` — these match the columns we added in DR.6.1.
- Keep legacy columns as Mapped attributes so SQLAlchemy doesn't complain about unmodeled columns: `user_id`, `two_factor_enabled`, `two_factor_method`, `two_factor_secret`, `is_active`.

**Risk:** code that reads `user.id` expecting a UUID will break (id is now bigint). The places to check:
- `api/src/app/core/auth/dependencies.py` — `get_current_user` returns the User
- `api/src/app/core/audit/service.py` — writes `user_id` (a UUID) into `audit_logs.user_id`
- Any `audit.log(..., user_id=user.id, ...)` call — switch to `user.legacy_uuid` so audit FK keeps validating

**Smoke after DR.6.3:**
```
docker logs template_api-api-1 | grep "Application startup complete"
# expect: app boots without SQLAlchemy mapper errors
```
**Rollback:** revert `models.py` to map back to `users`.

---

## DR.6.4 — Auth lookup reads from `tbl_user_login`

Update `api/src/app/core/auth/service.py`:
- The `login(...)` function currently does `select(User).where(User.email == ...)`. After DR.6.3 this WILL work as-is because the `User` model now points at `tbl_user_login`. But add an explicit `WHERE email IS NOT NULL` so the legacy `USR29684795` row with NULL email can never accidentally match an empty-string login attempt.
- `bcrypt.verify(plain, user.password_hash)` — works via the Python alias property on the model.

JWT issuance:
- Today the JWT carries `sub = str(user.id)` where `user.id` was UUID. Now `user.id` is bigint. The dependency that decodes the JWT — `get_current_user` — does `SELECT FROM users WHERE id = :sub`. After model swap, it'll do `SELECT FROM tbl_user_login WHERE id = :sub` — bigint comparison — works.
- BUT: any audit log that records `user_id` (UUID type in `audit_logs.user_id`) needs `user.legacy_uuid` not `user.id`.

**Smoke after DR.6.4:**
```
curl -X POST /api/v1/auth/login -d '{"email":"admin@core-demo.local","password":"Admin@123","org_slug":"core-demo"}'
# expect: 200 + JWT
# decode JWT: sub = a bigint string (e.g. "2")
```
**Rollback:** revert `service.py`.

---

## DR.6.5 — Update `/me`, `/_dev/demo-logins`, both seed scripts

- `api/src/app/core/users/router.py` (`/me`): the existing code is `select(User).where(User.id == ...)` followed by lookups for role + permissions + org. After DR.6.3 this works as-is.
- `api/src/app/core/dev/router.py` (`/_dev/demo-logins`): change the JOIN from `DemoCredential.user_id == User.id` to `DemoCredential.user_id == User.legacy_uuid`. One line.
- `api/src/app/scripts/seed_admin_user.py` and `seed_core_demo_org.py`: the existing inserts use fixed UUIDs as `User.id`. Now `User.id` is bigint (autoincrement), but `legacy_uuid` is where those UUIDs go. Switch the inserts to set `legacy_uuid` to the existing fixed UUIDs, use `ON CONFLICT (legacy_uuid) DO NOTHING` so re-runs are no-ops.

**Smoke after DR.6.5:**
```
curl /api/v1/_dev/demo-logins  # expect 4 entries
curl /api/v1/users/me with each of the 4 JWT tokens  # expect org block populated correctly
# Re-run both seed scripts  # expect "skipped" on every row (idempotent)
```
**Rollback:** revert each file.

---

## DR.6.6 — End-to-end smoke + park `users` table

- All 5 logins authenticate:
  - `admin@core-demo.local` / `Admin@123` → core-demo org → 12 sidebar entries
  - `owner@core-demo.local` / `Owner@123` → core-demo org → 12 entries (Owner can't users.write)
  - `employee@core-demo.local` / `Employee@123` → core-demo org → 8 entries
  - `admin@demo.local` / `Admin@123` → demo org → 16 entries (incl. furniture pack)
  - Legacy `USR29684795` via `/accounts/admin-login` → `/admin/dashboard` → still works
- `ng build --configuration development` clean (no Angular changes, but verify)
- Update the README in `tasks/phase-4.5-demo-roles-setup/` to mark DR.6 done
- **Do NOT drop the `users` table.** Mark it as orphaned. Track it for a 1–2 week revisit.

---

## Files to touch (total ~7 + 2 migrations)

| File | Action |
|---|---|
| `api/alembic/versions/0031_tbl_user_login_for_crm.py` | created |
| `api/alembic/versions/0032_migrate_users_to_tbl_user_login.py` | created |
| `api/src/app/core/users/models.py` | modified (User repointed) |
| `api/src/app/core/auth/service.py` | modified (lookup adjustments) |
| `api/src/app/core/users/router.py` | modified (/me uses legacy_uuid where needed) |
| `api/src/app/core/dev/router.py` | modified (join via legacy_uuid) |
| `api/src/app/scripts/seed_admin_user.py` | modified (insert into tbl_user_login + legacy_uuid) |
| `api/src/app/scripts/seed_core_demo_org.py` | modified (same) |

If a file we haven't listed turns out to need editing (audit service, dependency that reads `user.id`, etc.), STOP and re-confirm before changing.

## DB changes / migrations

- 0031 adds 9 columns + 2 partial unique indexes — all NULL-permissive, legacy row untouched
- 0032 inserts 4 rows, no UPDATEs, `WHERE NOT EXISTS` guard
- No DROP, no NOT NULL retrofitting, no constraint change to existing legacy data

## Tests to add

- `tests/test_dr6_auth_on_tbl_user_login.py`:
  - 4 demo emails authenticate and return JWT
  - `/users/me` returns the same shape (with org block) as before DR.6
  - `/_dev/demo-logins` returns 4 entries with correct labels
  - `tbl_user_login` row count = 5

## Verification checklist (one combined run after DR.6.6)

**Backend:**
- [ ] `alembic upgrade head` runs clean
- [ ] `SELECT COUNT(*) FROM tbl_user_login` returns 5
- [ ] `SELECT COUNT(*) FROM users` still returns 5 (orphan, NOT dropped)
- [ ] `POST /auth/login` returns 200 for all 4 demo emails
- [ ] `GET /users/me` returns `org` block correctly populated for all 4
- [ ] `GET /_dev/demo-logins` returns 4 entries
- [ ] Audit logs are still being written (test login attempts → check `audit_logs` table)

**Frontend:**
- [ ] `/accounts/login` dropdown shows 4 entries (unchanged from DR.4)
- [ ] Each preset auto-fills and login lands at `/user/...`
- [ ] Sidebar branding shows correct org name (unchanged from DR.5)
- [ ] `/accounts/admin-login` for legacy `USR29684795` still lands at `/admin/dashboard`

**Code review:**
- [ ] `grep -r "from src.app.core.users.models import User" api/` — every import still resolves
- [ ] No code reads `users` table directly (except the 0032 migration itself)
- [ ] No hardcoded "users" table name anywhere outside the migrations

## Self-check (10 rules)

- [ ] Rule 1 — no new pack→core import issues
- [ ] Rule 2 — `tbl_user_login` rows for FurnitureCRM all carry `org_id`; legacy row exempted by partial unique index
- [ ] Rule 8 — ~9 files; 2 migrations; each micro-step independently verifiable < 30 min
- [ ] Rule 10 — no TODOs; `users` is kept as a safety-net soak, not "fix later"

## Risks I'm explicitly tracking

1. **`audit_logs.user_id` is UUID.** Any `audit.log(user_id=user.id, ...)` after the model swap would try to write a bigint into a UUID column → constraint violation. Fix: pass `user.legacy_uuid` everywhere audit is called.

2. **JWT `sub` claim becomes a bigint string.** Anywhere code parses it as UUID, that breaks. Spot the parsers:
   - `get_current_user` (already SQL-typed, should be fine)
   - WebSocket auth (notifications module)
   - Staff portal token decoder (separate scope, should be fine)

3. **The 7-user seed in pack installer.** The furniture pack might write users via `User.__table__.insert(...)` somewhere — if so, that now hits `tbl_user_login`. Verify before DR.6.3.

4. **RLS policies.** `users` had RLS applied. `tbl_user_login` does not. If any code relies on RLS-as-it-applies-to-users, it'll break. Mitigation: this DR.6 doesn't add RLS to `tbl_user_login` — auth lookups don't need it. But document the gap.

5. **The legacy admin row has NULL email + NULL org_id.** Our queries must always include `WHERE email IS NOT NULL` (or filter by org explicitly) so the FurnitureCRM auth never accidentally matches the legacy row.

## Stop & report

After DR.6.6 smokes green, stop. Mark DR.6 Done in the README. Do **NOT** drop the `users` table. Write a short soak-checklist for the 2-week revisit.

If any sub-step (DR.6.1–DR.6.5) fails, stop immediately at that point, revert that sub-step, report the failure with the exact error, and DO NOT proceed.
