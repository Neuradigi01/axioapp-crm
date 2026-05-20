# Step 1 — Normal signup creates org + assigns Owner

**Goal:** When a visitor completes `/accounts/register` *without* an invite token, the system creates a brand-new organization, makes them its `Owner`, and lands them at `/user/dashboard` — all in one atomic transaction.
**Track:** RBAC, Ownership & Self-Signup
**Status:** Pending
**Depends on:** 1.5, 1.6, DR.7. Step 2 of this track (role templates) lands the seeding side; this step lands the *signup-routes-to-create-org* side. Ship Step 2 first so the new org has Admin/Employee on day one.

---

## Scope

A single signup branch — registration without an invite token — extended so it transactionally:

1. Inserts a new row into `organizations` (name derived from a signup-form field, or auto-generated `"<First Name>'s Workspace"` if not collected).
2. Calls into the role-template installer (delivered by Step 2) to seed `Owner`, `Admin`, `Employee` roles into the new org.
3. Inserts `tbl_user_login` + `tbl_user_info` rows for the user (existing legacy code path).
4. Inserts a `tbl_organization_members` row binding the new login to the new org with `role_id = <new_org's Owner role>`, `is_active = true`.
5. Returns JWT (existing logic).

The **invite-link branch** (`?token=…`) continues to flow through Phase 2.5.6's `POST /invitations/accept` — completely untouched. The two branches share no code beyond the user-creation primitives.

## What "normal signup" means

Distinguished by **absence of** an invite token in the request body / URL. If the body carries an `invite_token`, the existing 2.5.6 handler takes it. Otherwise this new handler takes it. One branch creates an org, the other joins one. They never overlap.

## Schema

No new tables. Possible single-column add to `organizations`:

| Column | Type | Why |
|---|---|---|
| `organizations.created_via` | TEXT NOT NULL DEFAULT `'normal_signup'` | Distinguishes self-signup orgs from seeded demo orgs (`'seed'`) and admin-provisioned orgs (`'admin'`). Useful for support/analytics; cheap. |

Migration `00XX_organizations_created_via.py` — one column add, backfill existing rows to `'seed'`, then set DEFAULT.

*(If the team decides this column is overkill, drop it — the step still works without. Confirm during step kickoff.)*

## Backend

| Endpoint | Auth | Behaviour |
|---|---|---|
| `POST /api/v1/auth/register` | unauthenticated | Body: `{email, password, first_name, last_name, phone, organization_name?, captcha?}`. Validates uniqueness of email. **Begins a transaction:** (a) insert `organizations`; (b) call `role_templates.install(org_id)` from Step 2 to seed roles; (c) insert `tbl_user_login` + `tbl_user_info`; (d) insert `tbl_organization_members` with `role_id = owner_role.id, is_active = true`; (e) commit. Returns the same `{access_token, refresh_token, user}` shape as login. If any step (b-d) fails, rolls back the whole thing — no orphaned orgs. |

**Reuse** the legacy template's `POST /auth/register` body validation + password hashing + email verification kickoff — wrap them in the new transactional flow. Do **not** rewrite password hashing or 2FA logic; the legacy code is preserved per CLAUDE.md.

**Email verification** — if the existing template requires it before first login, the new flow inherits that. The org + Owner row are created before verification (so the verification email can reference the org name); login is blocked until verified per the existing code.

## Frontend

`app/src/app/features/accounts/register/` — already exists with Material visuals (preserved per CLAUDE.md).

Two small additions:

1. **Optional "Workspace name" field** in the form (text, optional, defaults to `"<First Name>'s Workspace"` server-side if blank).
2. **On 200 success** with a fresh JWT, route to `/user/dashboard` (not the existing `/admin/dashboard` or a verification-pending page). The existing logic that handles "email verification pending" stays in place — if the backend says `verification_required: true`, that path still runs.

Existing visual treatment (Material card, captcha, password toggle) is unchanged.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/00XX_organizations_created_via.py` | created (if we keep the column) |
| `api/src/app/core/auth/router.py` | modified — extend `register` handler |
| `api/src/app/core/auth/service.py` | modified — new `register_with_new_org(...)` wrapping legacy primitives in a transaction; calls into `role_templates.install()` from Step 2 |
| `api/src/app/core/tenants/service.py` | modified — `create_organization(name, created_via)` helper (idempotent, returns the org) |
| `api/src/app/core/auth/schemas.py` | modified — add `organization_name` to `RegisterRequest` |
| `api/tests/test_normal_signup_creates_org.py` | created |
| `app/src/app/features/accounts/register/register.component.ts` | modified — add workspace_name field, route to `/user/dashboard` on success |
| `app/src/app/features/accounts/register/register.component.html` | modified — add the workspace_name input |
| `app/src/app/services/auth-api.service.ts` | modified — pass new field through |

**~9 files + 1 migration.** Within the per-step rule.

## Tests

`api/tests/test_normal_signup_creates_org.py`:

- **Happy path:** POST register with valid body → 201, response carries `access_token`. DB: one new `organizations` row; one `tbl_user_login` + `tbl_user_info`; one `tbl_organization_members` with `role_id = <owner of new org>`, `is_active = true`. The new org has exactly three `roles` rows (Owner, Admin, Employee).
- **Default workspace name:** omit `organization_name` → org named `"<First Name>'s Workspace"`.
- **Email uniqueness:** post twice with same email → 409 on second attempt.
- **Rollback on role-install failure:** monkey-patch `role_templates.install` to raise → assert NO `organizations`, `tbl_user_login`, `tbl_user_info`, or `tbl_organization_members` row landed (transaction held).
- **Login after signup:** the JWT returned is immediately usable on `/users/me` and resolves to the new org.

## Smoke

```
.\docker-helper.cmd upgrade   # apply 00XX migration if present
docker exec template_api-api-1 pytest tests/test_normal_signup_creates_org.py -v

# Browser:
#   /accounts/register
#   email=founder@example.com, password=Owner@123, first=Acme, last=Co, workspace=Acme Furniture
#   submit → email verification flow (existing) → click verify link → JWT issued → /user/dashboard
#   /user/settings/roles → three rows: Owner (locked), Admin (editable), Employee (editable)
#   /user/settings/users → one user (founder@example.com) with role=Owner
```

## Risks

- **Email verification dependency:** if the existing register flow blocks login until email is verified, the smoke walk takes a verification round-trip. Make sure the new transactional handler completes its DB writes *before* the verification email goes out — otherwise a user clicking the verify link before commits land is in a weird state. (Current legacy code commits before emailing — preserve that order.)
- **Race on `organization_name` collision:** organization names are not unique globally. No constraint, no race.
- **Captcha / rate-limit on register:** untouched. Existing protections continue.

## Rollback

Revert the 9 source files + downgrade the migration. No data lost in legacy tables (they only see additions). Any new orgs created via the new branch persist as orphan rows in the orgs table — not harmful, but ops can `DELETE FROM organizations WHERE created_via = 'normal_signup' AND id IN (...)` to clean up if desired.
