# Step 5 — Frontend: Leads Center two-row toolbar rebuild

**Goal:** Replace the current header-strip of chips + scattered dropdowns with sir's two-row toolbar: 9 filter cells + Search + Export (CSV) + a `(filtered/total)` count in the section header. Saved-views popover + advanced-filter modal stay accessible as small secondary buttons anchored to the right of row 2 — the DSL surface is load-bearing.
**Track:** Leads — Update Status Flow
**Status:** Pending
**Depends on:** Step 2 (`created_from`/`created_to` + `sort=next_follow_up_due` + `unfiltered_total` on the response).

---

## Scope

In-scope:

- Rebuild the header block of `leads.page.html` with:
  - Section title `Leads Center (filtered/total)` — count from Step 2's `unfiltered_total` + the existing `total`.
  - Right-aligned `Export (CSV)` link that issues `GET /leads/export.csv` with the toolbar's current query params.
  - **Row 1** (6 cells): Date (from), Between (to), Order By/As, Category Wise (stage), Source Wise, Data Search.
  - **Row 2** (5 cells): User, Status, Order Type, `Search` submit button (spans 2 cells), + right-anchored secondary buttons (Saved Views · Advanced Filter).
- All filter inputs use the floating-label outlined style from the Update Status modal (consistent look).
- Dropdowns use `crm-mobile-select` (app-wide convention).
- Filter state stored in a single signal `filters` that mirrors the query-string shape. `Search` button submits (URL update + refetch); pressing Enter in a text input triggers the same.
- URL is the source of truth — every filter round-trips through the query string so refresh / share-link / back-button all work.
- Mobile: two rows collapse to a single-column vertical stack under `sm:` breakpoint (640px). Saved Views + Advanced Filter fold into a "More" overflow menu on mobile.
- Preserve today's semantics of `assigned_to` — the User dropdown lists org users + a synthetic "— Unassigned —" entry that submits `unassigned_only=true` instead of `assigned_to=<uuid>`.
- Preserve today's semantics of the status filter — default `active` on first load if no `status` param in URL.

Out of scope:

- No Remarks filter cell (README D-list note; explanation there).
- No changes to the DSL / advanced-filter modal itself. It stays reachable as-is.
- No changes to the leads table body / row rendering.
- No changes to the saved-views storage / API.
- No new backend endpoints — Step 2 already added everything needed.

## DB changes / migrations

**None.**

## Files to touch

| File | Action |
|---|---|
| [`APP/src/app/features/user/core/leads/leads.page.ts`](../../APP/src/app/features/user/core/leads/leads.page.ts) | modified — consolidate scattered filter signals into one `filters` object; add `unfiltered_total`; add `onExportCsv`; keep advanced-filter + saved-views wiring |
| [`APP/src/app/features/user/core/leads/leads.page.html`](../../APP/src/app/features/user/core/leads/leads.page.html) | modified — replace the current chip-strip block with the two-row toolbar |
| [`APP/src/app/features/user/core/leads/leads-api.service.ts`](../../APP/src/app/features/user/core/leads/leads-api.service.ts) | modified — extend `list()` params with `created_from`, `created_to`; widen `sort` type; extend `LeadListResponse` with `unfiltered_total`; add `exportCsvUrl(params)` helper |

**3 files, ~500 LOC of template + ~150 LOC of TS.** The template hits the ~400 LOC ceiling; split the toolbar into a sub-component (`leads-toolbar.component.html/ts`) if it grows past 500. **Contingency: pre-split as a 4th and 5th file if the initial pass overshoots.**

## Plan

1. **Types.** Update `LeadListResponse` interface with `unfiltered_total: number`. Update `LeadListParams` interface with `created_from?: string`, `created_to?: string`. Widen the `sort` union type to include `'next_follow_up_due'`.
2. **`exportCsvUrl(params)` helper.** Returns a `SafeUrl` for the download link (no HTTP request from the service — just URL construction). Reuses the same param shape as `list()`.
3. **`filters` signal on the page.** Single object shape mirroring the query string:
   ```ts
   interface ToolbarFilters {
     created_from: string | null;
     created_to: string | null;
     sort: SortField;
     stage: string | null;         // Category
     source: LeadSource | null;
     q: string | null;             // Data Search
     assigned_to: string | null;
     unassigned_only: boolean;
     status: LeadStatus | 'all';
     order: 'asc' | 'desc';
   }
   ```
   Default from URL query params on init; sync back to URL on Search.
4. **Delete old chip-strip signals** (`statusChip`, `noActivityFilter`, `sortKey`, `sortOrder`, etc.) and replace with `filters` reads. Preserve the effect that re-fetches on filter change — but debounce to Search-button-click; do NOT auto-refetch on every keystroke (heavier server round-trips).
5. **`unfiltered_total`.** Read from response, expose as computed signal, render in `Leads Center ({{ filteredTotal() }}/{{ unfilteredTotal() }})`.
6. **Template — Row 1 grid.** `<div class="grid grid-cols-2 md:grid-cols-6 gap-3">` with 6 cells, each a floating-label input. Date/Between use `<input type="date">`. Others use `crm-mobile-select` where applicable, native `<input>` for `q` (Data Search).
7. **Template — Row 2 grid.** Similar; last two cells hold the `Search` button (full width) + the secondary-buttons row (Saved Views · Advanced Filter · optional "Reset" button that clears every filter and re-fetches).
8. **Enter key on `q` triggers Search.** `(keyup.enter)="onSearch()"`.
9. **Export click.** `<a [href]="exportCsvUrl(filters())" download>Export (CSV)</a>` — no HTTP client, browser handles the download.
10. **Advanced Filter + Saved Views** — keep the existing modal / popover components; just re-anchor their trigger buttons to row 2.
11. **Mobile responsive.** Use `grid-cols-1 sm:grid-cols-2 md:grid-cols-6` on row 1 and `grid-cols-1 sm:grid-cols-2 md:grid-cols-5` on row 2. On mobile the Saved Views + Advanced Filter buttons collapse into a `crm-mobile-select`-style overflow ("More…") — reuse existing pattern from campaigns/leads mobile overflow if one exists; otherwise use two stacked buttons under the Search.

## Tests

Unit (page-level):

1. **Filter default `active` on first load.** No `status` in URL → `filters().status = 'active'` → request sent with `status=active`.
2. **URL sync on Search.** Change stage to "won"; click Search → URL now contains `?stage=won`; `list()` called once with `stage: 'won'`.
3. **Enter on Data Search triggers Search.**
4. **`(filtered/total)` count.** Response `{total: 3, unfiltered_total: 45}` → header shows `Leads Center (3/45)`.
5. **Export URL matches active filters.** With `stage=won&created_from=2026-01-01` in `filters()`, `exportCsvUrl` returns `/api/v1/leads/export.csv?stage=won&created_from=2026-01-01`.
6. **`— Unassigned —` synthetic option** submits `unassigned_only=true`, not `assigned_to`.
7. **Reset button** clears every filter back to defaults + re-fetches.
8. **Sort dropdown includes `next_follow_up_due`.**

Manual smoke:

9. Open `/user/leads` in Ajay's Workspace. Header reads `Leads Center (23/23)`. Set stage=Proposal + created_from=today-7d. Click Search. URL updates; list shrinks; header reads `Leads Center (X/23)`. Click Export (CSV); browser downloads a CSV with only those X leads. Sort by "Next follow-up" → leads with upcoming follow-ups float to top. Resize browser to mobile width → toolbar collapses to single column; Advanced Filter still reachable via "More" overflow.

## Smoke

```powershell
cd APP; npm start
# Per test #9 above.

# Prettier format
npx --no-install prettier --write src/app/features/user/core/leads/leads.page.ts src/app/features/user/core/leads/leads.page.html src/app/features/user/core/leads/leads-api.service.ts
```

## Risks

- **Losing the "no-activity" filter.** Today's page has a "no activity for 7d/14d/30d" dropdown. Sir's toolbar doesn't include it explicitly. Options: (a) keep it as an eleventh cell (my recommendation — it's a real per-day-standup filter reps use), (b) fold it into Advanced Filter, (c) drop it entirely. **My call: (a)** — add it as a small second row of secondary controls, don't lose the feature. Confirm with sir if it should stay visible.
- **Filter shape drift with URL.** Any refactor of `filters` interface must round-trip through the URL correctly. Add a unit test that snapshots the URL → filters → URL round-trip.
- **Auto-refetch vs Search-button.** Current page probably auto-refetches on every dropdown change. Sir's UX suggests explicit Search. **My call: explicit Search-button.** Reduces server load; matches sir's screenshot; matches HubSpot/Zoho/Pipedrive UX (unsourced). Reversible.
- **Export size.** Existing endpoint caps at 50k rows. Toolbar exposes no cap warning; if a user filters to 60k rows and clicks Export, they get 50k silently. Small addition: check `filteredTotal() > 50000` and show a toast "Export truncated to 50 000 rows" before starting download. **Include this in the step.**
- **Template line count.** If the toolbar template pushes `leads.page.html` past ~500 LOC total, split into `leads-toolbar.component.html` (contingency noted in file-budget).

## Rollback

Revert the three files. Old chip-strip UI returns; URL round-trip and API contract are unchanged (the two new query params are optional server-side).
