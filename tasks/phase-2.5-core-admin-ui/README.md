# Phase 2.5 — Core CRM Admin UI

**A side initiative between Phase 2 and Phase 3.** Built after Phase 4.5/DR.7 lands, but numbered 2.5 because what it ships is *core CRM* scope — admin surfaces that any tenant (furniture, salon, gym, real estate, …) needs to self-onboard onto the template without a developer.

## Why this exists

After Phase 2 the core CRM has all its *operational* features (contacts, leads, walk-ins, tasks, appointments, calls, catalog, billing, conversations, reviews, campaigns, …) and DR.5–7 made the tenant model real (three-table user split, per-org sidebar branding). But there is no UI for:

| Gap | What's missing today |
|---|---|
| **Team management** | Admin can't add, deactivate, or change roles of users in their org. The `GET /users` endpoint exists; `POST /users`, `PATCH /users/{id}` don't. There's no Angular page consuming any of it. |
| **Role + permission management** | Roles are seeded from `pack.yaml` + `seed_*.py`. There's no way for a tenant admin to create a custom role ("Showroom Lead") or tweak grants ("let Sales Executives see audit logs"). |
| **Org settings** | `org_settings` table exists, the backend endpoint exists, but the only UI is per-org sidebar branding (DR.5). No way to edit org name, currency, tax rate, timezone. |
| **Self-service profile** | A user can't change their own name, email, phone, or password. No `/user/profile` page. |
| **Invitations** | A new user can only be added via DB seed. There's no "invite by email → recipient sets password → first login" flow. |

These five gaps are what prevents shipping the CRM as a real **template** that another company can adopt without us holding their hand. They are core-CRM scope (vertical-agnostic) — that's why Phase 2.5 (not 4.5 or 5.x).

## What this does NOT do

- Does not touch the legacy `/admin/...` template panel (CLAUDE.md rule).
- Does not change the layered RBAC schema (Phase 2.5 only fills in UIs + a few missing CRUD endpoints).
- Does not implement audit-log viewer UI — defer to Phase 6.1 (Reporting/Analytics depth).
- Does not implement 2FA enrolment UI — backend already supports it via the legacy auth code, but a polished setup flow is Phase 6 / a separate ticket.
- Does not implement SSO/OAuth — out of scope for v1 template.

## Acceptance criteria

A brand-new tenant — say a salon chain — can log in as their org admin and:

1. **Add a new user** by inviting them via email. The recipient gets a one-time link, sets a password, logs in.
2. **Change a user's role** from Employee to Owner via dropdown.
3. **Deactivate a user** so they can no longer log in (but historical data survives).
4. **Create a custom role** ("Receptionist") and tick the permission keys it should grant.
5. **Edit org settings** — name, currency, tax rate, timezone.
6. **Self-edit profile** — change first/last name, phone, password (current → new).

All without ever opening `psql`, the DB, or talking to us.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 2.5.1 | [Backend admin CRUD endpoints (users + roles + permissions)](step-2.5.1-admin-crud-backend.md) | Pending | ~1 day |
| 2.5.2 | [Frontend: Users management page](step-2.5.2-users-page.md) | Pending | ~1 day |
| 2.5.3 | [Frontend: Roles + permission grants page](step-2.5.3-roles-page.md) | Pending | ~1 day |
| 2.5.4 | [Frontend: Org settings page](step-2.5.4-org-settings-page.md) | Pending | ~½ day |
| 2.5.5 | [Frontend: Self-service profile page](step-2.5.5-profile-page.md) | Pending | ~½ day |
| 2.5.6 | [Backend + frontend: Invite-user flow (email link → set password → first login)](step-2.5.6-invite-flow.md) | Pending | ~1.5 days |

**Total: ~5–6 working days.** Each step is independently verifiable; pause and report after each.

## Dependencies

- DR.7 (three-table user split) — Done. `tbl_organization_members` is what the admin UI binds against.
- Phase 2 — Done. The layered RBAC machinery (`roles`, `role_permissions`, `permissions`) is what 2.5.3 manipulates.
- DR.5 — Done. Per-org branding is consumed by 2.5.4.

## File budget (rough estimate)

| Area | Files | Notes |
|---|---|---|
| Backend (2.5.1, 2.5.6) | ~6 new (routers, services, schemas) + 1 migration (invitation tokens) | All in `api/src/app/core/users/`, `core/permissions/`, `core/invitations/` (new module) |
| Frontend (2.5.2 – 2.5.5) | ~16 (4 pages × {component.ts, .html, .scss, service.ts}) | Lives under `app/src/app/features/user/core/admin/` |
| Frontend (2.5.6) | ~6 (invite page, accept page, link generation in users-page) | Mix of `accounts/` (acceptance) + admin/users (sending) |
| Tests | ~6 backend pytest files | Per-step minimal happy-path coverage |

**Total ~35 files.** Within the per-step rule of < 10 files / < 400 lines.

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`. All 2.5 scope is `core/`.
- ✅ Rule 2: Every new table (just `invitations` in 2.5.6) carries `org_id`, RLS applied.
- ✅ Rule 3: Custom fields layered model not affected (admin UI doesn't add fields).
- ✅ Rule 4: New forms (user-create, role-create) render statically; no DB-driven field defs needed because these are core schema tables, not custom-field-bearing entities.
- ✅ Rule 5: Sidebar registry unchanged — admin pages live under `/user/settings/...` which the existing core `settings` descriptor gates.
- ✅ Rule 6: Permission registry unchanged. We surface existing `users.read`/`users.write`/`roles.read`/`roles.write` keys.
- ✅ Rule 7: `pack.yaml` not touched.
- ✅ Rule 8: Each step verifiable in < 30 min (one page or one backend slice each).
- ✅ Rule 9: Stop-and-report after every step.
- ✅ Rule 10: No TODOs, no commented-out code; invite flow ships complete or not at all.

## After this mini-phase

- Cleanly resumed Phase 5.1 — Marketplace abstraction.
- The CRM template is genuinely self-onboardable; ready to give to a friendly first non-furniture customer for beta.
