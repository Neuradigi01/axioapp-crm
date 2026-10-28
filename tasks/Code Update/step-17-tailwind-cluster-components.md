# Step 17 — Tailwind cluster components (badge / button-group / icon-button)

**Goal:** Wrap the ~357 occurrences of the same long Tailwind classlists into three small shared components.
**Track:** Code Update — Frontend Polish
**Depends on:** none
**Status:** Not started

## Scope
**In-scope:**
- Create three standalone components in `core/shared/components/`:
  - `<app-badge variant="success|warning|danger|info|neutral" size="sm|md">` — wraps `inline-flex items-center px-3 py-1.5 rounded-md ...` clusters
  - `<app-button-group>` — wraps modal-footer button rows
  - `<app-icon-button icon="..." (click)>` — wraps table-action cell buttons
- Replace ~80 file occurrences.

**Out of scope:**
- Theming / dark mode.
- Replacing PrimeNG/Material in `features/accounts/` or `features/admin/`.

## Files to touch
- `core/shared/components/badge.component.ts` (create)
- `core/shared/components/button-group.component.ts` (create)
- `core/shared/components/icon-button.component.ts` (create)
- ~80 template files across `core/` and `packs/furniture/`

## Plan
1. Define each component with a tight props API.
2. Grep for the three classlist patterns; replace mechanically.
3. Browser smoke 4–5 representative pages to confirm no visual regression.

## DB changes / migrations
None.

## Tests to add
- One snapshot test per component.

## Verification checklist
- Visual smoke: Contacts list (badges + action cells), any modal (button group).

## Self-check (10 rules)
- [ ] No `<button class="inline-flex items-center px-3 py-1.5 rounded-md ...">` literals left where the badge component fits.

## Stop & report
Files changed · LOC removed · "Awaiting your 'proceed'".
