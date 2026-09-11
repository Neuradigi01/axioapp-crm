# Step 12 — Frontend `/user/settings/custom-events` list page

**Goal:** Admin+ view of custom events with Owner-only edit/delete affordances. Sidebar entry NOT added (Settings-tab pattern per README).
**Phase:** Custom Events track — step 12/17
**Depends on:** Step 6
**Status:** Pending

## Scope

**In-scope:**
- Route `/user/settings/custom-events` (Admin+ view).
- List columns: Name (display + unprefixed), Category, Occurrences (last 30d count from occurrences API), Last fired, Status (Active/Disabled), Actions.
- "Create event" button top-right (Admin+ can click).
- Row actions: View detail (Admin+); Edit + Soft-delete + Reactivate (Owner-only — hidden for Admin).
- Search + category filter.

**Out of scope:**
- Modal (Step 13).
- Detail page (Step 14).

## Files to touch
- `APP/src/app/features/user/core/settings/custom-events/list.page.ts/.html/.scss` (new).
- `APP/src/app/features/user/core/settings/custom-events/custom-events.service.ts` (new).
- `APP/src/app/features/user/core/settings/settings.routes.ts` (modified — add route).

## Plan
1. List page + service.
2. Permission-gated action buttons.
3. Search + filter.

## Tests to add
- Playwright: Admin sees list + Create button, no Edit/Delete buttons on rows.
- Playwright: Owner sees full actions.
- Playwright: search filters live.

## Verification checklist
- Frontend: prettier + eslint clean.
- Frontend: manual walk-through.

## Self-check
- [ ] Rule N/A / clean.
- [ ] Rule 8: 3 files.

## Stop & report
Await "proceed".
