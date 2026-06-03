# Onboarding & Pack Picker Setup

A focused track for the post-registration onboarding flow that lets a new user pick their organization name and CRM template (Core, Furniture, or one of several "Coming soon" verticals) before landing in `/user/dashboard`.

Sits outside the numbered phase tree — vertical-neutral, ship-when-ready. Builds directly on top of the now-shipped `rbac-ownership/` track.

## Why this exists

The `rbac-ownership/` track shipped a transactional signup that creates user + org + Owner role + Admin/Employee role templates in one atomic call at `POST /api/v1/auth/register`. The org is created with `pack_id = 'core'` hardcoded because the registration form has nowhere for the user to choose a vertical.

This means today's flow is:

- New customer signs up → gets a Core CRM org → cannot reach the Furniture pack without an ops engineer running the `install_pack` CLI script.

That is the gap. A furniture-store owner cannot self-serve into a furniture CRM. The vertical-pack architecture (built across Phase 1–4) is invisible to the end user.

| Gap | What's missing today |
|---|---|
| **Template choice at signup** | Furniture pack is built, installable, and registered — but no UI exposes it as a choice. New orgs default to `core`. |
| **Org name collection** | Today it's an optional field on `/accounts/register` (defaults to `"<First Name>'s Workspace"`). Needs to move to a dedicated onboarding page where it gets the focus it deserves. |
| **Pack installer not auto-run on signup** | `installer.install(org_id, pack_id)` works, but is only invoked via the CLI script. Self-serve orgs never call it. |
| **No "Coming soon" roadmap surface** | When a prospect asks "do you support real estate / clinics / etc.?", we have no in-product answer. |
| **Mid-onboarding abandonment recovery** | No guard catches a user who registers, closes the tab, and comes back later. They would hit `/user/...` with no org and break. |

These five gaps stand between "Furniture pack exists in the codebase" and "a furniture-store owner can sign up at 9 AM and be selling by 10 AM, with no human in the loop."

## What this does NOT do (preserved-as-is invariants)

- Does **not** change the auth core. JWT signing, password hashing, refresh tokens, 2FA (Google Authenticator + Email OTP + SMS OTP), email verification, forgot/reset password — all preserved per CLAUDE.md.
- Does **not** change the invite-link signup branch. `?token=<invite>` continues to hit Phase 2.5.6's `/invitations/accept` and skip onboarding entirely. Invited users already have an org.
- Does **not** change the role-template installer (delivered by `rbac-ownership/` Step 2). New orgs continue to auto-seed Owner / Admin / Employee role templates.
- Does **not** change the pack installer at `api/src/app/core/packs/installer.py`. The track *invokes* it at a new moment but does not modify its behavior.
- Does **not** add an `enabled_packs` array column. The existing `organizations.pack_id` single-string column is sufficient. Multi-pack stacking is a later concern.
- Does **not** modify the module registry, permission registry, RLS policies, or sidebar resolution. Pack selection only sets `pack_id`; everything downstream already filters off that.
- Does **not** modify the `/accounts/login`, `/accounts/forgot-password`, `/accounts/reset-password`, or 2FA challenge pages. Their existing PrimeNG / Angular Material visuals stay (per CLAUDE.md option-a styling decision).
- Does **not** modify `/admin/**` legacy routes. Untouched per CLAUDE.md.
- Does **not** modify `/staff-portal/**`. Out of scope.
- Does **not** ship Real Estate, Clinic, Sales, or any other vertical pack. Those are placeholder tiles only — `status: 'coming_soon'`, disabled in UI, blocked on backend.
- Does **not** implement an "add a second pack" flow for existing orgs. Pack switching / stacking is out of scope.
- Does **not** modify `Flutter/`. Untouched per CLAUDE.md. If the Flutter app calls `/auth/register`, the contract change in Step 2 (dropping `organization_name` from the request body) is breaking — confirm at Step 2 kickoff and decide handling.

## Acceptance criteria

A brand-new visitor, with no invite link, can:

1. **Register** at `/accounts/register` with email + password + first/last name (+ phone if existing schema requires) — **no organization name field**. Submit → 201, JWT issued with `needs_onboarding: true` claim. Redirected to `/onboarding`.
2. **Close the browser**, come back later, log in → redirected to `/onboarding` again. Cannot reach `/user/...` until onboarding finishes.
3. On `/onboarding`, see:
   - An "Organization name" required input.
   - A grid of template tiles, each with icon, name, one-line description, and "Coming soon" badge where applicable.
   - **Core CRM** and **Furniture CRM** selectable.
   - **Real Estate**, **Clinic / Dental**, **Sales CRM**, **Automotive**, **Salon & Spa**, **Fitness**, **Education**, **Hospitality** (and any others added to the catalog config later) shown as "Coming soon" — visible, disabled, not submittable.
   - Country and currency fields (currency auto-populates from the selected tile's `default_currency`).
4. Pick a tile + type an org name → submit → backend creates the org with the chosen `pack_id`, runs `installer.install(org_id, pack_id)`, assigns the user as Owner of the new org, issues a fresh JWT without the `needs_onboarding` claim, redirects to `/user/dashboard`.
5. Land on a fully-seeded org: pipelines from the pack manifest, custom fields, lead sources, currency, tax rate, AI defaults, follow-up templates — all live, no CLI step required.
6. Invited user (URL has `?token=...`): registers, never sees `/onboarding`, lands directly in the inviting org's `/user/dashboard`.
7. Attempt to submit a "Coming soon" pack via crafted request → 400, no org created.

All without any DB-level intervention or CLI installer step.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Pack catalog endpoint + static config](step-1-pack-catalog-endpoint.md) | Pending | ~½ day |
| 2 | [Backend: split signup, defer org creation, add onboarding endpoint](step-2-backend-split-signup.md) | Pending | ~1 day |
| 3 | [Frontend: simplified register + onboarding page + tiles UI](step-3-frontend-onboarding-page.md) | Pending | ~1 day |
| 4 | [Route guard: no-org → onboarding](step-4-no-org-route-guard.md) | Pending | ~½ day |

**Total: ~3 working days.** Each step independently verifiable; pause and report after each per rule 9.

## Dependencies

- `rbac-ownership/` track — **Done.** This track depends on Step 1 (signup creates org), Step 2 (role-template installer), Step 4 (route-guard pattern) being shipped. We extend, not replace.
- Phase 4 (Furniture pack) — **Done.** `packs/furniture/pack.yaml` + installer must exist for the Furniture tile to be selectable.
- Phase 1.5 / 1.6 (auth + JWT) — **Done.** This track adds one JWT claim (`needs_onboarding`) but does not touch signing/verification.
- Phase 1.7 (audit logs) — **Done.** New events (`org.created_via_onboarding`, `pack.installed_via_onboarding`) wire into the existing audit infra.

No new external dependencies. No new tables (one column add discussed in Step 2 and recommended **against**).

## File budget (rough estimate)

| Area | Files | Notes |
|---|---|---|
| Backend (Steps 1, 2) | ~5 new + ~6 modified | `core/packs/catalog_config.py`, `core/packs/router.py`, `core/packs/service.py`, `core/packs/schemas.py`, `core/auth/router.py`, `core/auth/service.py`, `core/auth/schemas.py`, `core/auth/jwt.py`, `core/tenants/service.py`, `core/users/router.py`. No migration. |
| Frontend (Steps 3, 4) | ~7 new + ~4 modified | `features/accounts/onboarding/` (component + service + sub-component + types), `features/accounts/register/` (form simplification), `features/user/core/shared/guards/no-org.guard.ts`, route wiring. |
| Tests | ~3 backend pytest files + 1 frontend spec | Per-step minimal coverage. |

**Total ~27 files across 4 steps.** Each step ≤ 10 files / ≤ 400 lines per rule 8.

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| Org cannot be created without a valid, selectable `pack_id` | `complete_onboarding` validates `pack_id` against the catalog's `available` packs. Coming-soon packs return 400. |
| One user → one org via signup | Onboarding endpoint refuses to run if the user already has a `tbl_organization_members` row. Idempotent: re-hitting it returns the existing org. |
| Onboarding cannot be skipped client-side | `noOrgGuard` reads server-validated state (`/users/me` → `needs_onboarding`). Frontend cannot bypass by URL manipulation. |
| Invite-link branch never touches onboarding | `/invitations/accept` (existing Phase 2.5.6) is the only path that joins to an existing org. Onboarding is the only path that creates a new org. They never overlap. |
| Pack installer always runs in the same transaction as org creation | `complete_onboarding` wraps `create_organization` + `role_templates.install` + `tbl_organization_members` insert + `installer.install` in one transaction. Failure rolls back the org. |
| Catalog config is the single source of truth for tile visibility | Frontend never hardcodes tile lists. `GET /api/v1/packs/catalog` is the only source. Adding a tile = one config edit, no UI deploy. |

## Self-check against the 10 rules

- ✅ Rule 1: `/core` never imports `/packs`. Catalog endpoint scans `packs/*/pack.yaml` via the existing pack registry — does not import pack code.
- ✅ Rule 2: Every table touched has `org_id` and RLS. We touch `organizations` (tenant root) and `tbl_organization_members` (already has both). No new tables.
- ✅ Rule 3: Custom fields layered model unaffected. The pack installer (unchanged here) handles `source: pack` field seeding.
- ✅ Rule 4: New forms (simplified register, onboarding) render statically — these are core schema fields, not dynamic-custom-field-bearing entities.
- ✅ Rule 5: Sidebar registry unchanged. `/onboarding` is a one-off route in the accounts feature, outside the module-registered tree.
- ✅ Rule 6: Permission registry unchanged. Onboarding is post-auth, pre-org; no permission keys involved.
- ✅ Rule 7: `pack.yaml` is the source of truth — the catalog reads from it, the installer reads from it. Catalog config only adds **placeholder** metadata for not-yet-built packs.
- ✅ Rule 8: Each step ≤ 10 files / ≤ 400 lines, verifiable in < 30 min.
- ✅ Rule 9: Stop-and-report after every step.
- ✅ Rule 10: No TODOs. Every step leaves the codebase clean and runnable.

## After this track

- The CRM is **truly self-onboardable end-to-end into the right vertical**: a stranger signs up, picks Furniture, and is selling chairs by lunch — no ops involvement, no CLI step.
- The pack catalog endpoint becomes a stable API contract reusable by future surfaces (marketing-site signup tiles, superadmin org-provisioning UI, "add a pack" upgrade flow when multi-pack lands).
- The "Coming soon" tiles give marketing and sales a credible in-product roadmap surface without engineering having to ship empty packs.
- Adding Real Estate (or any subsequent vertical) becomes: write `packs/real_estate/pack.yaml` + installer + UI modules → remove its entry from `PLACEHOLDER_PACKS` → the auto-discovery picks it up as `available`. No onboarding code changes needed.

## When to start

Whenever the user gives the go-ahead. No currently-active track blocks this one. The work is small, the architecture is in place, and the gap is real.
