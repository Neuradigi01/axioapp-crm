# Phase 4.5 — Demo Roles Setup (side task)

A side initiative between Phase 4 and Phase 5. **Not part of the master prompt's 76-step plan.**

## Why this exists

After Phase 4, the only org in the demo DB is `demo` with the furniture pack installed and one admin user (`admin@demo.local`). When you log in, you see *every* sidebar entry — including all the furniture-pack modules (Inventory, Custom Orders, Field Ops, Billing & POS).

This makes it hard to see what the **core CRM alone** looks like, and it makes it hard to test role-based access (Admin vs Owner vs Employee). This mini-phase fixes both:

1. Seeds a second org (`core-demo`) with **no furniture pack** so its sidebar shows only Layer-1 (core) modules.
2. Seeds three generic roles in that org — **Admin**, **Owner**, **Employee** — with carefully scoped permission grants.
3. Seeds one user per role.
4. Adds a tiny "Test logins" dropdown above the existing login form at `/accounts/login` so you can switch between the four test logins (3 in core-demo + 1 in demo) with one click.

After this you can demonstrate the two-layer architecture visually: same code, same running app, two completely different CRM experiences depending on which org you log into.

## What this does NOT do

- **Does not touch `/accounts/admin-login`** — the legacy admin button stays as-is. The dropdown only appears on `/accounts/login`.
- **Does not touch the existing `demo` org or `admin@demo.local`** — both keep working unchanged.
- **Does not touch any core or pack module source code.** No new endpoints, no new tables, no migrations.
- **Does not seed sample data** (contacts, leads, tasks) into `core-demo`. The org starts empty so the demo is the sidebar/permissions, not the data.
- **Does not install the furniture pack into `core-demo`.** That's the whole point.

## Acceptance criteria (when all 3 steps are done)

| Login | Sidebar entries visible |
|---|---|
| `admin@core-demo.local` / `Admin@123` | Contacts, Leads, Walk-ins, Appointments, Catalog, Calls, Conversations, Reviews, Campaigns, Tasks, Staff, Settings (full access). **No furniture modules.** |
| `owner@core-demo.local` / `Owner@123` | Same as Admin, but no `users.write` / `roles.write` (read-only team management). **No furniture modules.** |
| `employee@core-demo.local` / `Employee@123` | Day-to-day modules only — Contacts, Leads, Walk-ins, Appointments, Catalog (read), Conversations, Calls, Tasks, Billing (read). **No Staff, no Settings, no furniture modules.** |
| `admin@demo.local` / `Admin@123` *(existing)* | All core modules **plus** Inventory, Custom Orders, Field Operations, Billing & POS. |

## Steps

- [DR.1 — Seed core-demo org + 3 roles + 3 users](step-dr.1-seed-core-demo-org.md) — Done
- [DR.2 — Login dropdown for test logins](step-dr.2-login-dropdown.md) — Done
- [DR.3 — Smoke test all 4 logins side-by-side](step-dr.3-smoke-test.md) — Done
- [DR.4 — Move demo logins from hardcoded array to DB](step-dr.4-db-backed-logins.md) — Done
- [DR.5 — Per-org sidebar branding](step-dr.5-sidebar-branding.md) — Done
- [DR.6 — Move auth onto `tbl_user_login`](step-dr.6-auth-on-tbl-user-login.md) — Done

## DR.6 soak checklist — `users` table

After DR.6, FurnitureCRM auth reads from `tbl_user_login` only. The
old `users` table is kept physically intact (11 rows) as a 2-week
safety net so we can roll back without data loss. Revisit on or after
**2026-05-29** and run through this checklist:

- [ ] Audit-log review: confirm no `auth.*` or write-path audit rows
      have `user_id` values that aren't present as
      `tbl_user_login.legacy_uuid`.
- [ ] FK retarget plan: `auth_sessions.user_id`, `audit_logs.user_id`,
      `staff_sessions.user_id`, `staff_profiles.user_id`, and any
      `*.assigned_to_id` columns currently reference `users.id`. Plan
      a migration to retarget them to
      `tbl_user_login.legacy_uuid` (UNIQUE partial index already
      exists from migration 0031), then drop the FK + the `users`
      table + the placeholder `Table("users", …)` shim in
      [`api/src/app/core/users/models.py`](../../api/src/app/core/users/models.py).
- [ ] Verify the legacy `UserLogin` class in
      [`api/src/models/user.py`](../../api/src/models/user.py) is
      still the only declarative class that maps the bigint `id`
      column, and that the layered `User`
      class uses `__mapper_args__["exclude_properties"]` to keep
      `id`/`user_id`/`two_factor_*` off its mapper.
- [ ] Final cutover migration drops the placeholder `users` shim,
      drops the physical `users` table, retargets FKs.

## File budget

| File | Action | Step |
|---|---|---|
| `api/src/app/scripts/seed_core_demo_org.py` | created | DR.1 |
| `app/src/app/features/accounts/login/login.component.ts` | modified | DR.2 |
| `app/src/app/features/accounts/login/login.component.html` | modified | DR.2 |

**3 files total.** No migrations, no new tables, no new endpoints, no module changes.

## After this mini-phase

Resume the master plan at **Phase 5.1 — Marketplace Sync abstraction**.
