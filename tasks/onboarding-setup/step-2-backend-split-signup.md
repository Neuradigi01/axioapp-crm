# Step 2 — Backend: split signup, defer org creation, add onboarding endpoint

**Goal:** Change `POST /api/v1/auth/register` to create *only* the user (no org), issue a JWT carrying `needs_onboarding: true`, and add `POST /api/v1/auth/onboarding/complete` to create the organization + run the pack installer + assign Owner role + issue a fresh JWT.

**Track:** Onboarding & Pack Picker Setup
**Status:** Pending
**Depends on:** Step 1 (catalog endpoint — used to validate submitted `pack_id`).

---

## Scope

Splits the work `rbac-ownership/` Step 1 currently does atomically across two HTTP requests:

- **Request 1 — `POST /auth/register`** — creates `tbl_user_login` + `tbl_user_info` only. No org. No role assignment. No membership row. Issues a JWT carrying a custom claim `needs_onboarding: true`. Email verification kickoff (if configured) runs unchanged.
- **Request 2 — `POST /auth/onboarding/complete`** — accepts `{organization_name, pack_id, country?, currency?, team_size?}`. Validates `pack_id` against the catalog (must be `status="available"`). In one transaction: creates the org with the chosen `pack_id`, calls `role_templates.install(org_id)` (Owner + Admin + Employee), inserts `tbl_organization_members` with the user as Owner, calls `installer.install(org_id, pack_id)` to seed pack-specific data. Issues a fresh JWT **without** `needs_onboarding`.

The **invite-link branch** (`?token=…` → `/invitations/accept`, Phase 2.5.6) continues unchanged. Invited users never hit this flow.

## What this does NOT do

- Does **not** modify password hashing, 2FA logic, refresh-token logic, login, logout, forgot/reset password, or email verification. All preserved.
- Does **not** modify role-template content. We *call* the installer; we do not change what it installs.
- Does **not** modify pack installer code. We *call* `installer.install` at a new moment; its internals are unchanged.
- Does **not** modify the invite-link signup branch.
- Does **not** modify `register_with_new_org`. It is **kept as legacy** for backward compatibility with any direct callers (tests, seed scripts) but is no longer reachable from `/auth/register`. If after audit nothing calls it, can be removed in a follow-up.

## Schema

No new tables. One column add is considered and **recommended against**:

| Column | Type | Why considered | Why skipped |
|---|---|---|---|
| `tbl_user_login.onboarding_completed_at` | TIMESTAMPTZ NULL | Authoritative "needs onboarding?" answer without JWT parsing. | Same answer is derivable from `EXISTS (SELECT 1 FROM tbl_organization_members WHERE user_member_id = :uid AND is_active = true)` — which is the source of truth anyway. Adding a column duplicates state and risks drift. |

**Decision:** No migration. Derive `needs_onboarding` from membership existence in `/users/me`.

## Backend

### Endpoints

| Endpoint | Auth | Behaviour |
|---|---|---|
| `POST /api/v1/auth/register` | unauthenticated | Body: `{email, password, first_name, last_name, phone?, captcha?}`. **No** `organization_name`. Inserts `tbl_user_login` + `tbl_user_info`. Issues JWT with claims `{sub, token_id, needs_onboarding: true, ...}`. Returns `{access_token, refresh_token, user, needs_onboarding: true}`. Email verification kickoff (if `auth_config.contact_verification_mode` requires it) runs unchanged. If `organization_name` is submitted in the body, ignore it silently (do not 422) — keeps any pre-deploy clients working. |
| `POST /api/v1/auth/onboarding/complete` | bearer (any valid access token) | Body: `{organization_name, pack_id, country?, currency?, team_size?}`. Validates: `pack_id` exists in catalog with `status="available"`; `organization_name` non-empty. In one transaction: (a) `tenants.create_organization(name, pack_id, created_via='onboarding')`; (b) `role_templates.install(org_id)`; (c) insert `tbl_organization_members(user, org, Owner role, is_active=true)`; (d) `packs.installer.install(org_id, pack_id)`. Issues fresh JWT **without** `needs_onboarding`. Returns `{access_token, refresh_token, user, organization, needs_onboarding: false}`. |
| `GET /api/v1/users/me` | bearer (existing endpoint) | Extended: response includes `needs_onboarding: bool` derived from `EXISTS (active memberships for this user)`. Frontend route guard reads this. |

### Authorization rules on `/onboarding/complete`

| Scenario | Response |
|---|---|
| User has `needs_onboarding: true` JWT, no existing membership | Proceed. Create org. Issue fresh JWT. |
| User has `needs_onboarding: true` JWT, but membership already exists (race / replay) | **Idempotent**: skip creation, return the existing org + fresh non-onboarding JWT. |
| User has a normal JWT (no `needs_onboarding` claim) and an existing membership | **409 Conflict** `{"error": "already_onboarded"}`. Cannot create a second org via this endpoint. |
| `pack_id` not in catalog | **400** `{"error": "pack_not_found"}`. |
| `pack_id` exists but `status="coming_soon"` | **400** `{"error": "pack_not_available", "message": "<Pack name> is coming soon."}`. Frontend disables the tile, but backend is the enforcement boundary. |
| `organization_name` empty / whitespace | **422** standard validation error. |

### Audit events

Wire into the existing `audit_logs` infra (Phase 1.7) without breaking any existing event:

- `auth.user.registered` (or whatever the existing register-success event is named) — fires from `register_user_only`. Same shape as today.
- `org.created_via_onboarding` — new event, fires from `complete_onboarding` after the org row lands. Payload: `{org_id, pack_id, created_by_user_id}`.
- `pack.installed_via_onboarding` — new event, fires from `complete_onboarding` after the installer returns success. Payload: `{org_id, pack_id, pack_version}`.

## Frontend

None this step. Step 3 consumes the new endpoints.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/auth/router.py` | modified — `/register` simplified, `/onboarding/complete` added |
| `api/src/app/core/auth/service.py` | modified — split `register_with_new_org` into `register_user_only` + `complete_onboarding` (legacy function kept) |
| `api/src/app/core/auth/schemas.py` | modified — `RegisterRequest` drops `organization_name`; new `OnboardingCompleteRequest` and `OnboardingCompleteResponse` |
| `api/src/app/core/auth/jwt.py` (or wherever claim assembly lives) | modified — add optional `needs_onboarding` claim |
| `api/src/app/core/tenants/service.py` | modified — `create_organization(name, pack_id, created_via)` accepts pack_id (currently hardcoded to `'core'`) |
| `api/src/app/core/users/router.py` | modified — `/users/me` response includes `needs_onboarding: bool` |
| `api/tests/test_register_user_only.py` | created |
| `api/tests/test_onboarding_complete.py` | created |

**8 files total.** Within per-step rule.

## Tests

### `api/tests/test_register_user_only.py`

- POST `/register` with `{email, password, first_name, last_name}` → 201, response carries `access_token`. JWT decoded has `needs_onboarding=true`. DB: one `tbl_user_login` + one `tbl_user_info` row. **Zero** rows in `organizations`. **Zero** rows in `tbl_organization_members`. **Zero** rows in `roles` for this user.
- POST `/register` twice with same email → 409 on second attempt.
- POST `/register` with extra `organization_name` field → 201, field silently ignored, behaviour identical to call without it.
- POST `/register` → fetch `/users/me` with returned token → response includes `needs_onboarding: true`.

### `api/tests/test_onboarding_complete.py`

- **Happy path Furniture:** register → POST `/onboarding/complete` with `pack_id="furniture", organization_name="Acme Furniture"` → 200, fresh JWT without `needs_onboarding`. DB: one new org with `pack_id="furniture", name="Acme Furniture", created_via="onboarding"`. One membership with `role_id=<new Owner role>, is_active=true`. Three roles (Owner, Admin, Employee). Furniture-pack seeds present (sample: at least one pipeline named per `pack.yaml`, at least one custom field with `source="pack"`).
- **Happy path Core:** same with `pack_id="core"` → org created with `pack_id="core"`. Owner/Admin/Employee seeded. **No** furniture-specific pipelines/fields.
- **Coming-soon rejected:** `pack_id="real_estate"` → 400, no org created, no membership.
- **Unknown pack:** `pack_id="blockchain"` → 400.
- **Empty org name:** `organization_name=""` → 422.
- **Already onboarded:** register → complete onboarding → call complete onboarding again with a different pack_id → 409.
- **Idempotency:** simulate the race: parallel onboarding-complete requests for the same user (use threading or the testclient's concurrent helper) → exactly one org lands. Second request returns the same `org_id`. No duplicate memberships.
- **Rollback on installer failure:** monkeypatch `packs.installer.install` to raise → assert no `organizations` row, no `tbl_organization_members` row, no `roles` rows from `role_templates.install` for this attempt. Transaction held.
- **users/me before onboarding:** returns `needs_onboarding: true`, no `organization` field.
- **users/me after onboarding:** returns `needs_onboarding: false`, `organization: {id, name, pack_id}`.

## Smoke

```powershell
.\API\docker-helper.cmd up
docker exec template_api-api-1 pytest tests/test_register_user_only.py tests/test_onboarding_complete.py -v

# Manual curl walkthrough (PowerShell):
$body = '{"email":"founder@acme.test","password":"Owner@123","first_name":"Acme","last_name":"Co"}'
$r1 = Invoke-RestMethod -Uri http://localhost:8000/api/v1/auth/register -Method Post -Body $body -ContentType 'application/json'
$T1 = $r1.access_token

Invoke-RestMethod -Uri http://localhost:8000/api/v1/users/me -Headers @{Authorization="Bearer $T1"}
# Expect: needs_onboarding=true, no organization

$ob = '{"organization_name":"Acme Furniture","pack_id":"furniture"}'
$r2 = Invoke-RestMethod -Uri http://localhost:8000/api/v1/auth/onboarding/complete -Method Post -Body $ob -ContentType 'application/json' -Headers @{Authorization="Bearer $T1"}
$T2 = $r2.access_token

Invoke-RestMethod -Uri http://localhost:8000/api/v1/users/me -Headers @{Authorization="Bearer $T2"}
# Expect: needs_onboarding=false, organization.pack_id=furniture
```

## Risks

- **`/auth/register` body contract change.** Dropping `organization_name` is a behaviour change. Old clients that send it still work (we silently ignore the field), but their expectation that "an org is created" is broken. Audit at kickoff:
  1. `Flutter/` — does it call `/auth/register`? Per CLAUDE.md, Flutter is untouched. If it calls this endpoint expecting org creation, decide: (a) flag-gated rollout, (b) keep legacy `register_with_new_org` reachable on a different path like `/auth/register/legacy`, or (c) accept the break since Flutter is not part of FurnitureCRM.
  2. Any embedded widget JS or external integrations.
  3. CI/seed scripts in this repo.
- **`needs_onboarding` JWT claim collision.** Verify no existing claim name collides. JWT libs ignore unknown claims, so old token decoders tolerate this; new code must not assume the claim is always present (old refresh tokens issued before deploy won't carry it — derive from `/users/me` as authoritative).
- **Transactional rollback edge:** the pack installer may itself open sub-transactions or batch commits. Verify it participates in the parent transaction (uses the passed session, doesn't commit independently). If it commits early, wrap with a savepoint or refactor the installer to take a session. Decide at kickoff after reading `installer.install` signature.
- **Email verification ordering.** Existing code commits user rows *before* sending the verify email so the email's link works on click. New `register_user_only` preserves that order — commit then email. Do not reverse.

## Rollback

Revert the 8 files. No migration to downgrade. Orphan users created during the new flow (registered but did not complete onboarding) remain as `tbl_user_login` rows with no membership. On rollback to legacy single-step register, these users would not be able to log in cleanly (the legacy login expects a membership). Mitigations:

- **Option A:** Leave them. Their next login attempt errors out; they re-register. Low volume during a single rollback window.
- **Option B:** One-time ops script — for each orphan, call `complete_onboarding(org_name=default, pack_id='core')` to give them a Core org so they can log in. Document at deploy time if this is preferred.
