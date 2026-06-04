# Step 5 — Onboarding wizard: 3-step guided flow (template → name → details)

**Goal:** Convert the current single-page onboarding form into a guided 3-step wizard.
- **Step 1:** Pick CRM template tile
- **Step 2:** Type organization name (header echoes "Setting up your **<Template>**")
- **Step 3:** Country + currency (pre-filled) + team size

Each step has its own panel, a progress indicator, and Continue / Back / Finish-setup buttons. Same backend endpoint, same dark mode, same tile component — only the panel layout and navigation are new.

**Track:** Onboarding & Pack Picker Setup
**Status:** Pending
**Depends on:** Step 3 (existing onboarding page + form) — COMPLETED.

---

## Why this step exists

Step 3 shipped the onboarding page as a single form with all fields visible at once: organization name + tile grid + country/currency/team size, every input on one screen. Manager feedback on 2026-06-04 — modern SaaS onboarding (Slack, Notion, Linear, HubSpot, Monday, Stripe) is a **guided wizard**, not a dump-everything form. One decision per page → lower cognitive load → higher completion rate → users feel onboarded rather than processed.

This step refactors the layout into a 3-step wizard while preserving every existing behaviour underneath (backend call, dark mode, tile component, currency pre-fill, error handling, auth bounce, route guard integration).

### Why "template first"

The single most important decision a new user makes is **which vertical their business is**. Everything else (pipelines, custom fields, currency, terminology, modules) flows from that choice. Putting the tile picker on Step 1 — before the user has typed a single character — matches what HubSpot, Monday, Airtable, Webflow, Typeform do. The alternative (workspace name first, à la Slack/Notion) is right for single-product tools, not multi-vertical SaaS.

## What this does NOT do

- Does **not** change the backend. `POST /api/v1/auth/onboarding/complete` is unchanged.
- Does **not** change the API contract. Same `OnboardingCompleteRequest` and `OnboardingCompleteResponse` shapes.
- Does **not** change the pack tile component (`pack-tile.component.ts`). The same tile renders inside the new Step 1 panel.
- Does **not** change dark mode styling. Step 3's `dark:` variants carry through every panel.
- Does **not** introduce a new route. Still served at `/onboarding`.
- Does **not** add new fields or remove existing ones. `organization_name`, `pack_id`, `country`, `currency`, `team_size` all stay.
- Does **not** change the registration flow, the no-org route guard, `/users/me`, or any auth-service signal.
- Does **not** require API restart, DB migration, seed, or Alembic work.
- Does **not** ship animated panel transitions. The MVP is instant swap (`@if` panel switch). Easy to add later if asked.

## Wizard structure

One `<form>` (same `FormGroup` as today, so all field values persist across step changes). Three conditionally-rendered panels driven by a `currentStep` signal (0 / 1 / 2):

| # | Title | Panel content | Footer |
|---|---|---|---|
| **1** | "What kind of CRM do you need?" | Tile grid (existing `<app-pack-tile>` component, no change) | `Continue →` — disabled until a `status="available"` tile is selected |
| **2** | "Name your workspace" + small badge echoing the selected template ("Setting up your **Furniture CRM**") | Single org-name text input | `← Back` + `Continue →` — disabled until `organization_name` non-empty and trimmed |
| **3** | "A few last details" | Country, currency (pre-filled from selected tile's `default_currency`), team-size dropdown | `← Back` + `Finish setup` — disabled while submitting |

### Progress indicator

Subtle, top-of-card. Either:
- **Dots:** `● ● ○` (filled = current/done, hollow = upcoming) — minimal, modern (Linear style)
- **Text:** `Step 2 of 3` — clearer, explicit (Stripe style)

Recommend **both together** as a single row: `Step 2 of 3` text on the left, three dots on the right. Reads cleanly at a glance.

### Step-1 footer alignment

Step 1 has only one button (`Continue →`). Steps 2 and 3 have `← Back` on the left, `Continue →` / `Finish setup` on the right. Keep the right-side button at the same x-position across all three steps so the user's cursor doesn't have to chase it.

## UX rules

- **Back preserves state.** Going back from step 2 → step 1 keeps the tile selection (it's a signal, not a step-local). Forward again, the same tile is still selected. Same for org_name when navigating back from step 3 → step 2.
- **Forward validates.** Continue is disabled until that step's required fields are valid. No mid-step error toast — the disabled button is the signal.
- **Final submit only on step 3.** Steps 1 and 2's buttons advance the step counter. Only step 3 calls the API.
- **Loading state on step 3.** While the API request is in flight, the submit button shows "Setting up…" and disables. Other inputs on the page disable to prevent edits mid-call.
- **API errors stay on step 3.** Existing snackbar pattern (per Step 3) surfaces error messages. User's inputs are preserved so they can retry without redoing the wizard.
- **Enter-key behaviour.** Submitting the form natively (Enter in an input) only triggers the API call on step 3. On steps 1 and 2, Enter advances to the next step if validity passes — matches user expectation.
- **Keyboard nav.** Tab/Shift-Tab cycle within the active panel only. Buttons are reachable. Inactive panels are not in the tab order (use `@if` not `[hidden]`).
- **Coming-soon tiles on step 1.** Still dimmed, still not clickable, still don't trigger `Continue` to enable. Existing pack-tile component handles this.
- **Auth bounce.** The defensive `isAuthenticated()` check in `ngOnInit` (Step 3) stays. Unauthenticated visitors get bounced to `/accounts/login` *before* any wizard panel renders.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/accounts/onboarding/onboarding.component.ts` | modified — add `currentStep` signal (0/1/2), `next()` / `back()` methods, per-step validity computed signals (`canAdvanceStep1`, `canAdvanceStep2`), wire `onSubmit` to fire only on step 3 |
| `APP/src/app/features/accounts/onboarding/onboarding.component.html` | modified — wrap each step's content in `@if (currentStep() === N)` panels; add progress indicator row at the top of the card; split footer into per-step Back/Continue/Finish-setup buttons |

**2 files. Pure frontend refactor.** ~~`pack-tile.component.ts`~~ and ~~`onboarding-api.service.ts`~~ stay as-is.

## Acceptance criteria

A brand-new user can:

1. Register → land on `/onboarding` showing **Step 1 of 3** with the tile grid. `Continue →` is disabled.
2. Click a Coming-soon tile → no state change, button still disabled.
3. Click **Furniture** → tile gets the selected ring + checkmark → `Continue →` enables.
4. Click `Continue →` → Step 2 renders. Header echoes "**Furniture CRM**". Org-name input is empty. `Continue →` disabled, `← Back` enabled.
5. Click `← Back` → Step 1 renders. Furniture is still selected.
6. Click `Continue →` again → Step 2. Type "Acme Furniture" → `Continue →` enables.
7. Click `Continue →` → Step 3. Country = "India", Currency = "INR" (pre-filled from selected tile), Team size empty.
8. Click `← Back` → Step 2. Org name is still "Acme Furniture".
9. Click `Continue →` → Step 3. Pick team size "1-5".
10. Click `Finish setup` → loading state on button → API call → redirect to `/user/dashboard`.
11. Org in DB: `name="Acme Furniture"`, `pack_id="furniture"`, `currency="INR"`, `tax_rate=18.0`.
12. **Dark mode parity:** toggle theme, walk the same flow, every panel renders correctly with `dark:` variants.
13. **API error recovery:** simulate failure (stop API container, click Finish setup) → snackbar with error → user stays on Step 3 with inputs intact → restart API → click again → succeeds.

## Tests

### Browser smoke (manual — primary)

The 13 acceptance-criteria walkthrough steps above.

### Frontend unit (optional, skip per Step 3/4 convention)

`onboarding.component.spec.ts` cases that would matter:
- `currentStep()` starts at 0
- `next()` advances and `back()` retreats
- `canAdvanceStep1()` is false until a selectable tile is picked
- `canAdvanceStep2()` is false until org_name is non-empty
- `onSubmit()` is a no-op when `currentStep() !== 2`
- Submit on step 3 calls the existing onboarding API

Recommendation: skip the unit spec (TestBed setup is non-trivial relative to the value; browser smoke covers the same ground at runtime, and Step 2's backend pytest catches any wire-shape regression). If shipped later, append to the existing Step 3 spec file.

### Backend tests

**None added.** Backend behaviour is unchanged from Step 2. The 14 existing tests (`test_register_user_only.py` + `test_onboarding_complete.py`) continue to cover the API.

## Manual work required after deploy

| Action | Needed? |
|---|---|
| Backend migration / seed / upgrade | ❌ No backend changes |
| API container restart | ❌ Backend untouched |
| Angular dev server restart | ⚠️ Usually HMR picks it up; if not, restart `npm start` |
| Browser hard-refresh | ✅ `Ctrl+Shift+R` to clear bundle cache |

## Risks

- **Form validation rewiring.** Today's onboarding form is plain Tailwind with one validator (`Validators.required` on `organization_name`). Per-step "can advance" checks read individual control validity — already supported by `FormGroup`. No mat-error/Material wiring depends on the form being a single panel. Low risk.
- **State persistence across step changes.** `FormGroup` lives on the component instance, so values persist regardless of which panel is rendered. The `selectedPackId` signal is component-level too — also persists. By design.
- **"Setting up your <Template>" header echo on step 2.** Requires the selected tile's display name. Already exposed via the `selectedTile` computed signal (added in Step 3). No new lookup needed.
- **Enter-key form submission.** Native `<form>` Enter triggers `(ngSubmit)`. If the user hits Enter on step 1, `onSubmit()` runs. Mitigation: `onSubmit()` is gated by `currentStep() === 2`. Otherwise it advances the step. Same handler, branched logic.
- **Progress indicator overflow.** Three steps fit on any viewport, but if the indicator wraps awkwardly on 320px-wide phones, simplify to text-only ("Step 2 of 3").

## Rollback

Revert the 2 files. The pre-wizard single-form layout returns. No data lost, no schema affected, no API change to undo.

## After this step

The onboarding flow looks and feels like a modern SaaS onboarding: focused, guided, low-friction. A new customer signs up, picks "Furniture CRM" in 5 seconds, types their workspace name, fills three small details, and is in the dashboard. Total time: under 2 minutes, three deliberate clicks.

When you eventually add more polish (animated transitions between panels, a "Welcome" splash before step 1, a "Setup complete!" confetti on step 3 submit), each of those is a small append to the wizard — not a rewrite. The 3-panel skeleton is the foundation.
