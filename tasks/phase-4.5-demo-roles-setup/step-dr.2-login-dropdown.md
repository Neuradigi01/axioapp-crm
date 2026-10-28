# Step DR.2 — Login dropdown for test logins

**Goal:** Add a small "Test logins" dropdown above the existing login card at `/accounts/login` so the four seeded test users (3 in `core-demo` + 1 in `demo`) can be picked with one click, auto-filling the form. The legacy Material card stays untouched.
**Phase:** 4.5 — Demo Roles Setup (side task)
**Depends on:** DR.1
**Status:** Pending

## Scope

**In-scope:**
- Modify `app/src/app/features/accounts/login/login.component.ts`:
  - Add a typed `demoPresets` array (4 entries — see table below).
  - Add a `selectedOrgSlug = signal<string>('demo')` field. (Defaults to `'demo'` so behaviour before any dropdown change is identical to today.)
  - Add an `applyPreset(preset)` method that sets `loginForm.controls.identifier`, `loginForm.controls.password`, and `selectedOrgSlug`.
  - Change the one line that hard-codes `DEFAULT_FURNITURE_ORG_SLUG` in the user-login submit handler to use `this.selectedOrgSlug()`.
- Modify `app/src/app/features/accounts/login/login.component.html`:
  - Add ONE new `<div>` block ABOVE the existing `<mat-card>` — Tailwind-styled, labelled "Test logins", containing a `<select>` and a tiny "Active org: X" caption.
  - The block is rendered only on the user-login variant (i.e. when `isAdmin === false` — bound to the existing route data flag the component already uses).

**Out of scope:**
- Touching `/accounts/admin-login` — explicit user instruction. The legacy admin button + flow stays as-is.
- Restyling the existing Material card.
- Changing the password helper / forgot-password / 2FA flows.
- Auto-submitting the form when a preset is picked — user still clicks "Sign in" themselves.

## Preset entries

| Label shown in dropdown | identifier (email) | password | orgSlug |
|---|---|---|---|
| `Core CRM — Admin` | `admin@core-demo.local` | `Admin@123` | `core-demo` |
| `Core CRM — Owner` | `owner@core-demo.local` | `Owner@123` | `core-demo` |
| `Core CRM — Employee` | `employee@core-demo.local` | `Employee@123` | `core-demo` |
| `Furniture CRM — Admin` | `admin@demo.local` | `Admin@123` | `demo` |

A blank first option `— Pick a test login —` is the default so the page loads with an empty form (same as today).

## Files to touch

- `app/src/app/features/accounts/login/login.component.ts` (modified)
- `app/src/app/features/accounts/login/login.component.html` (modified)

## Plan

1. In the `.ts`:
   - Declare `interface DemoPreset { label: string; identifier: string; password: string; orgSlug: string }`.
   - Declare `readonly demoPresets: DemoPreset[]` (4 entries, hardcoded).
   - Declare `readonly selectedOrgSlug = signal<string>('demo')`.
   - Add `applyPreset(preset: DemoPreset)` that calls `this.loginForm.patchValue(...)` and `this.selectedOrgSlug.set(preset.orgSlug)`.
   - Change `this.furnitureAuth.login(identifier, password, DEFAULT_FURNITURE_ORG_SLUG)` → `this.furnitureAuth.login(identifier, password, this.selectedOrgSlug())`.
   - Remove the `DEFAULT_FURNITURE_ORG_SLUG` constant if it's no longer referenced anywhere else. If it is, keep it.
2. In the `.html`:
   - Render the new block only when `!isAdmin` (existing flag).
   - Tailwind-styled card: white background, subtle ring, small padding, label "Test logins", a native `<select>` with the 4 presets + a default blank, and `<p>Active org: {{ selectedOrgSlug() }}</p>` below.
   - Wire `(change)` on the `<select>` to call `applyPreset(...)` with the matched preset.
3. Verify the Material form keeps working without the dropdown: with the blank option selected, submitting still uses `selectedOrgSlug='demo'` (today's behaviour preserved exactly).

## DB changes / migrations

None.

## Tests to add

None — this is a UI affordance for testing. The `ng build` type-check is the verification.

## Verification checklist

**Frontend:**
- `cd app && npx ng build --configuration development` → completes with no TS errors.
- Visit `/accounts/login` → the "Test logins" dropdown appears ABOVE the existing Material card.
- Visit `/accounts/admin-login` → the dropdown is NOT shown; legacy admin form behaves as before.
- Pick "Core CRM — Admin" → `identifier` fills with `admin@core-demo.local`, `password` fills with `Admin@123`, caption reads "Active org: core-demo".
- Click "Sign in" → land at `/user/...` → sidebar shows only core modules.
- Logout → pick "Furniture CRM — Admin" → submit → sidebar additionally shows Inventory / Custom Orders / Field Ops / Billing & POS.
- Pick the blank default → fields clear, caption reverts to "Active org: demo" → submit with manual credentials still works (regression check).

**Code review:**
- Open the `.ts` — confirm the `loginForm` form group definition is untouched.
- Confirm the existing 2FA / captcha / forgot-password paths are unchanged.
- Confirm no edits to `account-services/`, `core/auth/`, or anything outside the two files listed.

## Self-check (10 rules)

- [ ] Rule 8 — Two files, well under 50 lines of new code.
- [ ] Rule 10 — No TODOs, no commented-out code, no shortcuts.
- [ ] The legacy admin login path (`/accounts/admin-login`) is verifiably untouched.
- [ ] Tailwind only on the added block; no new Material imports.

## Stop & report

Demo through both Core and Furniture logins, capture sidebar screenshots if useful, stop, report. Await "proceed" before DR.3.
