# Step DR.1 — Seed `core-demo` org + 3 roles + 3 users

**Goal:** Create a second organization in the demo DB that has no furniture pack installed, with three generic roles (Admin / Owner / Employee) and one user per role, so the core CRM can be exercised in isolation from the furniture pack.
**Phase:** 4.5 — Demo Roles Setup (side task)
**Depends on:** Phase 4 complete (all 12 steps).
**Status:** Pending

## Scope

**In-scope:**
- One new idempotent seed script: `api/src/app/scripts/seed_core_demo_org.py`.
- The script inserts (all with `ON CONFLICT DO NOTHING` so re-runs are safe):
  - One `organizations` row: `slug='core-demo'`, `name='Core CRM Demo'`, `pack_id=NULL`, `pack_version=NULL`, `currency='INR'`, `tax_rate=0.00`, `timezone='Asia/Kolkata'`.
  - Three `roles` rows (all `is_system=true`): **Admin**, **Owner**, **Employee**.
  - `role_permissions` rows expanding the permission grants listed below.
  - Three `users` rows with hashed passwords (one per role).
  - One `org_settings` row for the new org (so the billing engine has defaults to read).
- The script reads existing rows in the `permissions` table (already populated at app startup by the module registry) and grants by `key`. It does NOT create new permissions.

**Out of scope:**
- Sample data (no contacts, leads, tasks, appointments, etc.) — the org starts empty.
- Furniture pack install — must NOT run on this org.
- Frontend changes (those land in DR.2).

## Permission grants

| Role | Permissions (by key) |
|---|---|
| **Admin** | `users.read`, `users.write`, `roles.read`, `roles.write`, `audit.read`, `custom_fields.read`, `custom_fields.write`, `settings.read`, `settings.write`, `contacts.read`, `contacts.write`, `leads.read`, `leads.write`, `appointments.read`, `appointments.write`, `walk_ins.read`, `walk_ins.write`, `catalog.read`, `catalog.write`, `conversations.read`, `conversations.write`, `calls.read`, `calls.write`, `calls.outcomes.manage`, `reviews.read`, `reviews.write`, `campaigns.read`, `campaigns.write`, `campaigns.send`, `tasks.read`, `tasks.write`, `pipelines.read`, `pipelines.write`, `activities.read`, `activities.write`, `staff.read`, `staff.write`, `attendance.write`, `notifications.read`, `notifications.write`, `billing.read`, `billing.write`, `billing.refund` |
| **Owner** | Same as Admin **minus** `users.write`, `roles.write`, `billing.refund`. (Read-only on team / role config and refunds.) |
| **Employee** | `contacts.read`, `contacts.write`, `leads.read`, `leads.write`, `activities.read`, `activities.write`, `tasks.read`, `tasks.write`, `appointments.read`, `appointments.write`, `walk_ins.read`, `walk_ins.write`, `catalog.read`, `conversations.read`, `conversations.write`, `calls.read`, `calls.write`, `billing.read`, `pipelines.read` |

**No** `inventory.*`, `pos.*`, `custom_orders.*`, `field_visits.*` for any of these. That's what makes the org "core-only".

## Users to seed

| Email | Password | Role | Full name |
|---|---|---|---|
| `admin@core-demo.local` | `Admin@123` | Admin | Core Demo Admin |
| `owner@core-demo.local` | `Owner@123` | Owner | Core Demo Owner |
| `employee@core-demo.local` | `Employee@123` | Employee | Core Demo Employee |

Passwords are hashed via `src.app.shared.security.password.hash_password` (same helper the existing admin seed uses).

## Files to touch

- `api/src/app/scripts/seed_core_demo_org.py` (created)

## Plan

1. Mirror the structure of `seed_demo_org.py` + `seed_admin_user.py` for layout.
2. Use `RequestContext` with `org_id=<new org>` so the `TenantScoped` mixin lets us insert rows under RLS.
3. Insert org → flush → roles (one per role) → flush → permissions lookup → role_permissions inserts → users → org_settings.
4. Print a summary table at the end (rows created vs skipped).
5. Make every insert use `pg_insert(...).on_conflict_do_nothing(...)` so re-running is a no-op.

## DB changes / migrations

None. Uses existing tables only.

## Tests to add

None for this step — it's a one-off seed script, not production code. The verification commands below double as the smoke test.

## Verification checklist

**Backend (commands you run):**
- `docker exec template_api-api-1 python -m src.app.scripts.seed_core_demo_org` → prints a "created N rows" summary.
- Re-run the same command → all rows report "skipped (already exists)". (Idempotency check.)
- Inspect the result:
  ```sql
  SELECT name, perms FROM (
    SELECT r.name, COUNT(rp.permission_id) AS perms
    FROM roles r LEFT JOIN role_permissions rp ON rp.role_id = r.id
    WHERE r.org_id = (SELECT id FROM organizations WHERE slug='core-demo')
    GROUP BY r.name
  ) ORDER BY name;
  ```
  → 3 rows: Admin (~41), Owner (~39), Employee (~19).
- `POST /api/v1/auth/login` with body `{"email":"admin@core-demo.local","password":"Admin@123","org_slug":"core-demo"}` → 200, returns a JWT.
- `GET /api/v1/modules` with that token's Authorization header → response array contains core modules only (`contacts`, `leads`, ..., `billing`) but NOT `inventory`, `custom_orders`, `field_ops`, `fp_billing`.

**Frontend:**
- Not yet — DR.2 wires the dropdown. For DR.1 verification you log in via curl / Postman.

**Code review:**
- Open the new seed script — confirm it uses `ON CONFLICT DO NOTHING` on every insert.
- Confirm it does NOT import anything from `src.app.packs.*` (rule 1).
- Confirm it does NOT call the pack installer.

## Self-check (10 rules)

- [ ] Rule 1 — Script lives under `core/scripts/` and does not import packs.
- [ ] Rule 2 — All inserted rows carry `org_id` (verified by RLS not erroring).
- [ ] Rule 6 — Permissions are looked up by `key` from the already-populated `permissions` table; not created here.
- [ ] Rule 7 — No pack-specific values (currency-rate decisions, tax-rate decisions) are hardcoded; the new org uses generic defaults.
- [ ] Rule 8 — One file, < 200 lines.
- [ ] Rule 10 — No TODOs, no commented-out code.

## Stop & report

After running the seed and verifying via curl, stop and report. Await "proceed" before DR.2.
