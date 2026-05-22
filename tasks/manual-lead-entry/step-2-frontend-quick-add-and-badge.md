# Step 2 — Frontend: quick-add floating button + source badge on list

**Goal:** Surface the new `source` column on the leads list as a small badge per row, and add a global floating "+" button to the app shell that opens the existing lead-form modal from any `/user/...` page. Permission-gated to `leads.create`.
**Track:** Manual Lead Entry
**Status:** Pending
**Depends on:** Step 1 (backend `source` field + audit event), Phase 1.10 (app shell), Phase 2.12 (Leads frontend), Phase 1.5 (permissions on the frontend).

---

## Scope

In-scope:

- New `quick-add-fab.component.{ts,html}` rendered in the app shell layout. Floating bottom-right (`fixed bottom-6 right-6 z-40`). Tailwind only.
- Clicking opens the existing `LeadFormModalComponent` (no behaviour change to that component).
- FAB is hidden when `!perms.has('leads.create')`.
- FAB is hidden on the staff-portal route tree (its own shell).
- Source badge component (small inline) in `leads.page.html` — one of `Manual | Bulk import | Widget | Google Ads | Meta Ads`, color-coded:
  - `manual` → gray
  - `bulk_import` → indigo
  - `widget` → emerald
  - `google_ads` → amber
  - `meta_ads` → blue
- Update `leads-api.service.ts` only if the existing `Lead` interface doesn't already accept arbitrary extra fields — add `source: 'manual' | 'bulk_import' | 'widget' | 'google_ads' | 'meta_ads'`.

Out of scope:

- No filter-by-source on the list yet — orgs will likely want it after bulk-import lands; deferred to the bulk-import track.
- No edit-source UI. `source` is immutable post-create (enforced by the backend not exposing it on `LeadUpdate`).
- No equivalent FAB on the staff portal — staff use the walk-in flow, not lead creation.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/shared/quick-add-fab/quick-add-fab.component.ts` | created |
| `app/src/app/features/user/shared/quick-add-fab/quick-add-fab.component.html` | created |
| `app/src/app/features/user/layout/user-shell.component.html` | modified — render `<app-quick-add-fab />` once near the bottom |
| `app/src/app/features/user/core/leads/leads.page.html` | modified — add the source badge to each row |
| `app/src/app/features/user/core/leads/leads-api.service.ts` | modified (small) — widen the `Lead` interface with `source` |

**5 files.** Inside rule-8 budget.

## Plan

1. Define a `LeadSource` TS literal type alias in `leads-api.service.ts` matching the backend enum exactly. Add `source: LeadSource` to the `Lead` interface.
2. In `leads.page.html`, render the badge next to the lead title (or in its own narrow column on the existing layout — implementer's call based on current grid). Tailwind class table:

   ```html
   @switch (lead.source) {
     @case ('manual')       { <span class="rounded-full bg-gray-100 text-gray-700 px-2 py-0.5 text-xs">Manual</span> }
     @case ('bulk_import')  { <span class="rounded-full bg-indigo-100 text-indigo-700 px-2 py-0.5 text-xs">Bulk import</span> }
     @case ('widget')       { <span class="rounded-full bg-emerald-100 text-emerald-700 px-2 py-0.5 text-xs">Widget</span> }
     @case ('google_ads')   { <span class="rounded-full bg-amber-100 text-amber-700 px-2 py-0.5 text-xs">Google Ads</span> }
     @case ('meta_ads')     { <span class="rounded-full bg-blue-100 text-blue-700 px-2 py-0.5 text-xs">Meta Ads</span> }
   }
   ```
3. Build `quick-add-fab.component.ts`: standalone, signals, `inject(PermissionsService)`, `inject(MatDialog)` (or whatever modal opener the existing leads page uses — match the pattern). Computed signal `canCreate = computed(() => this.perms.has('leads.create'))`. Click handler opens `LeadFormModalComponent` and on success navigates to `/user/leads`.
4. Place the FAB in `user-shell.component.html` exactly once, outside the `<router-outlet>` so it persists across navigation. Wrap with `@if (canCreate())` so it disappears for read-only users.
5. Smoke in the browser per the checklist below.

## Tests

Frontend testing in this project follows the existing pattern (mostly E2E + manual smoke; few unit tests). For this step:

- Smoke per the checklist. No new Jest test required.
- If the existing leads page has a unit test that asserts row contents, extend it to assert the badge renders. Otherwise skip.

## Smoke (browser)

```
1. Log in as Owner. From /user/dashboard, see the floating "+" bottom-right.
   Click it. Lead form modal opens. Create a lead. Modal closes; toast confirms.
   Navigate to /user/leads. The new lead appears with a gray "Manual" badge.

2. Log in as an Employee with no leads.create permission. The FAB is not rendered.

3. Navigate to /staff-portal/* (PIN-login flow per Phase 3). The FAB is not
   rendered there (different shell).

4. On the leads list, seed (or insert via DB) a lead with source='widget'.
   Refresh. Confirm the green "Widget" badge appears for that row.

5. Resize the viewport to mobile (375px). The FAB doesn't overlap key actions
   on /user/leads (e.g. the stage-column scroll). Acceptable: it floats over
   the bottom-right corner of the kanban which is usually empty.
```

## Risks

- **FAB collision with other floating elements:** the existing app may already have a chat widget or notification toast at bottom-right. Check `user-shell.component.html` and any global overlays. If conflict, shift the FAB to bottom-left and document the choice.
- **Source badge visual weight:** badges next to lead titles can clutter dense list rows. If the leads page uses the kanban layout (which it does — `lead-card.component.html`), the badge belongs **on the card**, not the page. Implementer makes the call at edit time — if the page is purely kanban, edit `lead-card.component.html` instead of `leads.page.html`.
- **Modal vs. drawer convention drift:** if other "create X" flows in the app use a drawer (PrimeNG sidebar) rather than a modal, match that pattern instead of introducing a new modal. The FAB just routes to the existing form, whatever shape it has.

## Rollback

Delete the new component folder. Remove the FAB include from `user-shell.component.html`. Revert the badge edit in `leads.page.html` (or `lead-card.component.html`). Revert the type widening in `leads-api.service.ts`. No DB state to roll back.
