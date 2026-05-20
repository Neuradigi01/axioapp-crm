# RBAC, Ownership & Self-Signup

A focused track for the role/permission/ownership surface that turns the CRM into a true self-onboarding template. Sits outside the numbered phase tree — vertical-neutral, ship-when-ready, picked up after Phase 2.5 lands the admin CRUD foundation.

## Why this exists

Phase 2.5 ships the admin UI for managing users, roles, permission grants, org settings, and invitations. What it does **not** ship is the *product behaviour* an Owner-driven SaaS needs:

| Gap | What's missing today |
|---|---|
| **Normal signup → new org + Owner** | Today, registration on `/accounts/register` creates a user but does not create an organization or assign Owner. New users land orphaned. There is no UI flow where "I sign up alone" becomes "I own a new workspace." |
| **Admin / Employee as role templates** | `roles` is per-org. Step 2.5.3 treats the seeded set as fixed system roles. There is no concept of a *template registry* — a vertical-neutral source of presets that gets stamped into a new org on creation, and which an Owner can re-pull from later. |
| **Ownership transfer** | Owner is a forever role on the original signup user. No flow exists to hand the org over to another member. Migrations and demos all stuck on whoever clicked Register first. |
| **Frontend route guards** | `canActivate` / permission-key gating exists on individual sidebar items, but there's no consistent guard layer: `/billing`, `/admin/users`, `/reports` rely on UI-hiding alone. Hitting the URL directly slips through. |
| **Security audit events** | `audit_logs` infra (Step 1.7) is in place, but no module emits `invitation.sent`, `role.assigned`, `permission.modified`, `ownership.transferred`, or the 401/403 unauthorized-access events the spec calls for. |
| **"Access Denied" page** | Hitting a forbidden route or being blocked by a guard currently surfaces as a router 404 or a silent redirect. No styled deny page. |

These six gaps are what stand between Phase 2.5 (admins can run their org) and a CRM template that a stranger can sign up for on Monday and have their team productive by Tuesday — without us provisioning anything.

## What this does NOT do

- Does not change the layered RBAC schema (`roles`, `role_permissions`, `permissions`). Those are already correct.
- Does not change the three-table user model (`tbl_user_login` / `tbl_user_info` / `tbl_organization_members`) from DR.7. This track binds against it.
- Does not implement audit-log viewer UI — defer to Phase 5.5 (Reporting/Analytics depth).
- Does not implement SSO / OAuth signup — out of scope for v1 template.
- Does not implement email verification on the new signup branch — the existing flow already covers it; Step 1 just routes through it.
- Does not add new permission keys to existing modules. The registry (Rule 6) is composed from what's already there.
- Does not allow an Owner to escalate themselves to Super-Admin or grant cross-org access. One Owner per org; one org per Owner-role row.

## Acceptance criteria

A brand-new visitor, with no invite link, can:

1. **Sign up** at `/accounts/register` → a new organization is created → they are assigned the fixed `Owner` role of it → they land at `/user/dashboard`.
2. The new org auto-seeds with `Owner` (assigned to them), `Admin`, and `Employee` roles, each pre-populated with the template's permission grants. The `Admin` and `Employee` rows are editable / deletable; `Owner` is locked.
3. They open `/user/settings/roles` → see three rows → can click **+ Add from template** and pull in additional presets (when more are defined, e.g. Sales Manager).
4. They invite a colleague via `/user/settings/users` (Phase 2.5.6 invite flow). The invite link's `role` param resolves against the role they just instantiated.
5. They transfer ownership to that colleague → colleague becomes Owner → original Owner is demoted to Admin → previously-Owner-only routes now 403 for them.
6. **Unauthorized URL access is blocked:**
   - Employee opening `/user/settings/users` → redirected to `/user/access-denied` with a styled message.
   - Admin opening `/user/settings/billing` → same.
   - Anonymous visitor opening any `/user/...` → redirected to `/accounts/login`.
7. **Every security-relevant action writes an audit row:** invitation sent / accepted / revoked; role created / edited / deleted; permission grant changed; ownership transferred; failed 401/403 attempts.

All without any DB-level intervention.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Normal signup creates org + assigns Owner](step-1-normal-signup-creates-org.md) | Pending | ~1 day |
| 2 | [Role-template registry + auto-seed on org creation](step-2-role-templates-auto-seed.md) | Pending | ~1 day |
| 3 | [Ownership transfer (backend + UI)](step-3-ownership-transfer.md) | Pending | ~½ day |
| 4 | [Frontend route guards + Access Denied page](step-4-route-guards-access-denied.md) | Pending | ~½ day |
| 5 | [Security audit events wiring](step-5-security-audit-events.md) | Pending | ~½ day |

**Total: ~3–4 working days.** Each step independently verifiable; pause and report after each per rule 9.

## Dependencies

- Phase 1.5 (users / roles / permissions schema) — Pending.
- Phase 1.6 (JWT auth) — Pending.
- Phase 1.7 (audit_logs infra) — Pending. Step 5 wires events into the table this step creates.
- DR.7 (three-table user split) — **Done.** `tbl_organization_members` is what Steps 1 and 3 bind ownership against.
- Phase 2.5 — Pending. Steps 2.5.1 (admin CRUD), 2.5.3 (roles page), 2.5.6 (invite flow) supply the surfaces this track extends. **Do not start any step here until 2.5 lands.**

## File budget (rough estimate)

| Area | Files | Notes |
|---|---|---|
| Backend (Steps 1, 2, 3) | ~10 new + ~4 modified + 2 migrations (`role_templates`, `organization_members.transferred_at` if needed) | Lives in `api/src/app/core/auth/`, `core/tenants/`, `core/permissions/` |
| Frontend (Steps 1, 3, 4) | ~10 new (signup-success, transfer-modal, access-denied page, guards) + ~4 modified (register flow, settings menu, app shell) | Lives under `app/src/app/features/accounts/`, `features/user/core/settings/`, `features/user/core/shared/guards/` |
| Audit wiring (Step 5) | 0 new files, ~6 modified call-sites | Edits service-layer code in `invitations`, `permissions`, `users`, `auth` to call `audit.log(...)` |
| Tests | ~5 backend pytest files | Per-step minimal coverage |

**Total ~30 files across 5 steps.** Within the per-step rule of < 10 files / < 400 lines.

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| Exactly one `Owner` per org | `tbl_organization_members`: partial unique index `WHERE role_id = <owner_role_id> AND is_active = true` |
| `Owner` role cannot be edited, deleted, or unassigned without transfer | `roles.is_system = true` AND `roles.name = 'Owner'` short-circuits all PATCH/DELETE; transfer endpoint is the only mutation path |
| Normal signup always creates a new org | Backend `POST /accounts/register` (or the legacy equivalent it routes through) wraps signup in a transaction that creates `organizations` + `tbl_organization_members` + role assignment. Failure rolls back atomically. |
| Invite-link signup never creates a new org | The invite-accept handler (Phase 2.5.6) is the *only* path that joins to an existing org. The new-signup handler is the *only* path that creates one. They never overlap. |
| Frontend route guards are permission-keyed, not role-name-keyed | `permissionGuard('billing.read')` not `roleGuard('Owner')` — keeps the gating composable with custom roles. |
| Audit events are write-best-effort | Failure to write an audit row never breaks the parent action (existing Step 1.7 contract). |

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`. All scope is `core/auth`, `core/tenants`, `core/permissions`, `core/audit` — vertical-neutral.
- ✅ Rule 2: One new table at most (`role_templates`, optional — could also be code-defined). If a table is added, it is **global** (templates are not tenant-scoped), so no `org_id`. The records *instantiated from* it land in the existing `roles` table which already has `org_id` + RLS.
- ✅ Rule 3: Custom fields layered model unaffected.
- ✅ Rule 4: New forms (signup-extras, transfer modal) render statically — these are core schema fields, not custom-field-bearing entities.
- ✅ Rule 5: Sidebar registry unchanged. New routes (`/user/access-denied`) added through the existing core route tree.
- ✅ Rule 6: Permission registry unchanged. Track *consumes* existing keys; it does not invent new modules.
- ✅ Rule 7: `pack.yaml` untouched. Role templates here are **vertical-neutral defaults** — furniture-specific roles still come from the furniture pack's `pack.yaml` per Rule 7.
- ✅ Rule 8: Each step verifiable in < 30 min (one slice each).
- ✅ Rule 9: Stop-and-report after every step.
- ✅ Rule 10: No TODOs. No "I'll wire the audit event later" — Step 5 closes the loop.

## After this track

- The CRM is **truly self-onboardable** end to end: a stranger signs up, builds out their team, hands over the keys when they retire, all without our involvement.
- The remaining Phase 2.5 work (admin CRUD, invite flow, profile page) has a real signup funnel feeding it.
- Phase 5 / Phase 6 land into a hardened tenant model where ownership and authorization are no longer "best-effort UI hiding."
