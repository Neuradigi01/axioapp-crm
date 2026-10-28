# Dev Tools UI

A focused track for **developer-only UI affordances** — surfaces that exist purely to make local development, smoke testing, and demos faster. None of this code ships to production: every component is gated behind `environment.showDevTools` (or equivalent) and tree-shakes out of the prod bundle.

## Why this exists

DR.2 added a "Test logins" dropdown directly into `login.component.html` so developers can pick from the seeded demo users with one click. It works, but:

- The dropdown sits **inside the production login card**, visually dominating a page real visitors will land on.
- It's only one-flag-away from accidentally shipping to prod.
- As we add more dev affordances (impersonate-user, switch-org, seed-reset, audit-log peeker, feature-flag toggles), we'd accumulate more cruft on production-facing pages.

A dedicated track for this work means:

1. Production login / register / dashboard look exactly like what a real customer sees on day one.
2. Every dev affordance lives in one mental bucket: `dev-tools-ui/`. New devs onboard faster.
3. Env-gating is consistent — one pattern, one flag, one boundary.

## What this track does

- Replaces the inline demo-login dropdown with a **floating dev pill** in the bottom-right corner, only visible when `environment.showDevTools === true`.
- Establishes the pattern for future dev-only UI: one component per affordance, all rendered from a single `<app-dev-toolbar>` host, all behind the same env flag.

## What this does NOT do

- Does not delete the underlying demo-login data — `/api/v1/_dev/demo-logins` endpoint and the seeded users from DR.1 / DR.4 stay exactly as they are.
- Does not change which test users exist, what their roles are, or how `selectedOrgSlug` flows into the login submit handler.
- Does not introduce a new env flag from scratch if Angular's `environment.ts` already exposes a usable one — reuse what's there.
- Does not add any backend changes. Pure frontend refactor + relocation.
- Does not touch `/accounts/admin-login` — explicit instruction from DR.2, carried forward.

## Acceptance criteria

In **dev mode** (`ng serve` / `environment.development.ts`):

1. `/accounts/login` shows a clean Material login card with **no** inline test-logins dropdown.
2. A small floating pill labelled **🛠 Demo logins** sits in the bottom-right corner of every page (login, register, forgot-password, and once authenticated, the app shell too — visible everywhere).
3. Clicking the pill opens a popover containing the same four demo presets DR.2 currently ships.
4. Picking a preset on the login page auto-fills the email + password fields and sets the active org slug, exactly as today.
5. Picking a preset while already authenticated logs out + logs back in as the chosen user (or, if simpler, just navigates to `/accounts/login` with the form pre-filled).

In **prod mode** (`ng build`):

1. The pill component is **not rendered** — not even as an empty DOM node. Verified via `View Source` on a prod build.
2. The dev-only routes (if any) are absent from the route tree.
3. The bundle does not contain the demo-preset strings (`admin@core-demo.local`, etc.). Verified via `grep` on the built JS.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Demo logins floating pill (replaces DR.2 dropdown)](step-1-demo-logins-floating-pill.md) | Pending | ~½ day |

**Total: ~½ day for now.** This track will grow as more dev affordances surface.

## Dependencies

- DR.2 — Pending. This track's Step 1 **replaces** DR.2's inline dropdown. If DR.2 lands first, Step 1 here is a refactor. If we leap-frog DR.2 (skipping the inline dropdown entirely), Step 1 here becomes the *only* place demo-login UX lives — adjust DR.2's status to Superseded in that case.
- `environment.development.ts` exposing a `showDevTools: true` (or equivalent) flag. If it doesn't yet, Step 1 adds it.

## File budget (rough estimate)

| Area | Files | Notes |
|---|---|---|
| New component | 3 — `demo-logins-pill.component.{ts,html,scss}` | Lives under `app/src/app/features/dev-tools/` (new folder) |
| Host integration | 1 modified — `app.component.html` (or `accounts-layout.component.html`) | One `<app-demo-logins-pill>` tag, env-gated |
| Login cleanup | 2 modified — `login.component.{ts,html}` | Remove the inline dropdown markup + state, keep `selectedOrgSlug` signal (still needed for submit) |
| Env flag | 1 modified — `environment.development.ts` (and `environment.ts` for parity, set to `false`) | If `showDevTools` doesn't exist yet |

**~6–7 files. No backend. No migrations.**

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| Dev components never render in prod | `@if (environment.showDevTools)` wrapping every dev component at its host site |
| Dev components live under one folder | `app/src/app/features/dev-tools/` — easy to grep, easy to gate, easy to delete if needed |
| Demo credentials are not bundled into prod | Tree-shaking via the env-gate; verified by smoke (`grep` on built JS) |
| No dev affordance bleeds into production-facing UX | Production layouts (`accounts-layout`, `user-layout`, `staff-portal-layout`) host the toolbar component, but the toolbar itself self-gates |

## Self-check against the 10 rules

- ✅ Rule 1: No backend touched. `core/` ↔ `packs/` separation unaffected.
- ✅ Rule 2: No DB changes.
- ✅ Rule 3: Custom fields unaffected.
- ✅ Rule 4: No new forms beyond the relocated dropdown.
- ✅ Rule 5: Sidebar registry unaffected.
- ✅ Rule 6: Permission registry unaffected.
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: Single step, < ½ day, < 10 files.
- ✅ Rule 9: Stop-and-report after step.
- ✅ Rule 10: No TODOs. Env-gating is unambiguous — either rendered or not, never half-shipped.

## After this track

- The login page looks production-ready from day one.
- Future dev affordances slot into `dev-tools/` without polluting customer-facing pages.
- A natural home exists for the "impersonate user", "switch org", "audit-log peeker" affordances we'll likely want during Phase 2.5 / 3 / 4 development.
