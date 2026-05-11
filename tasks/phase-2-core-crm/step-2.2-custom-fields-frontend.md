# Step 2.2 — Custom Fields engine: frontend (Settings UI)

**Goal:** Build the Settings → Custom Fields page where the user picks an entity, sees fields with badges (System/Pack/User), can add a user field, rename labels, hide, reorder via drag-and-drop. Tailwind only.
**Phase:** 2
**Depends on:** 2.1, 1.10
**Status:** Pending

## Scope
**In-scope:**
- New module `app/src/app/features/user/core/custom-fields/`:
  - `custom-fields-api.service.ts` — list/create/update/delete + render endpoint.
  - `custom-fields.page.ts` — entity-type picker (dropdown: contact, lead, walk_in, ...), field list table with badges, add/edit/delete, drag-handle.
  - `field-form.component.ts` — modal/dialog for create+edit user fields (key, label, type, required, options for select).
- Drag-and-drop: `@angular/cdk/drag-drop` (already in repo or add). On drop → call `PATCH /custom-fields/{id}` with new `display_order` (or a bulk reorder endpoint added in 2.1 stretch).
- Badges: green `System`, blue `Pack`, gray `User`. System/Pack fields show only label/order/required edits; user fields show full edit + delete.
- Hook page into Settings stub from 1.10 — Settings page becomes a tabbed layout with "Custom Fields" tab.

**Out of scope:**
- Other Settings tabs — Phase 3.

## Files to touch
- `app/src/app/features/user/core/custom-fields/custom-fields-api.service.ts` (created)
- `app/src/app/features/user/core/custom-fields/custom-fields.page.ts/.html` (created)
- `app/src/app/features/user/core/custom-fields/field-form.component.ts/.html` (created)
- `app/src/app/features/user/core/settings/settings-page.component.ts/.html` (modified — tabs)
- `app/src/app/app.routes.ts` (modified)

## Plan
1. Build the API service (typed signals/observables).
2. Settings page becomes a tab host. Tab "Custom Fields" loads the page component.
3. Page: signal for entity-type, signal for fields. On change → reload.
4. Drag list using cdk-drop-list; on drop, optimistic update + persist; revert on error.
5. Field form: reactive form with key (disabled on edit), label, type, required, options (for select/multiselect: comma-separated input that persists as `{choices: [...]}`).
6. Badge component reused across system/pack/user.

## Tests to add
- None (skipTests). Manual smoke per checklist.

## Verification checklist
**Frontend:**
- visit `/settings` → Custom Fields tab → pick "contact" → list renders.
- click "Add Field" → modal → submit → row appears with `User` badge.
- drag a row → order persists on reload.
- click delete on a system field → button disabled or hidden.

## Self-check (10 rules)
- [ ] No hardcoded form fields (rule 4).
- [ ] No imports from `packs/`.
- [ ] Tailwind for new page; no PrimeNG/Material introduced.

## Stop & report
Await "proceed" before Step 2.3.
