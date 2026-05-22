# Step 6 — Frontend: import history + error-report download

**Goal:** Build `/user/leads/import-history` — a paginated list of every import this org has ever run, with status, counts, uploader, timestamp, source platform, and download links for both the original source file and the error report. Gives ops a forensic trail for "where did this lead come from" investigations.
**Track:** Bulk Import
**Status:** Pending
**Depends on:** Step 1 (`GET /leads/import` list endpoint), Step 2 (error CSV download).

---

## Scope

In-scope:

- New route `/user/leads/import-history`.
- `HistoryPageComponent` — table of imports with columns:
  - Date (relative, with absolute on hover).
  - Name.
  - Source platform (badge with consistent colour from the manual-entry track).
  - Uploaded by (user name + avatar).
  - Status (badge).
  - Counts (compact: `957 ✓ · 32 dup · 11 err`).
  - Actions (kebab menu): "Download source", "Download errors" (only if errors > 0), "Cancel" (only if status is `mapping_committed` or `processing`).
- Pagination: 20 per page, server-side via `?page=&page_size=` on `GET /leads/import`. Add page params to the endpoint if missing in Step 1 — small addendum.
- Filtering: status dropdown (`All | Awaiting mapping | Processing | Completed | Failed | Cancelled`) + source platform dropdown.
- Sidebar menu entry "Import history" under Leads, gated by `leads.import`.
- Empty state: "No imports yet. [Start an import →]" with a button linking to `/user/leads/import`.

Out of scope:

- No bulk actions (delete N imports).
- No editing of completed imports (re-run a fixed CSV).
- No diff view (show me what changed between two imports).

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/leads/import/history-page.component.ts` | created |
| `app/src/app/features/user/core/leads/import/history-page.component.html` | created |
| `app/src/app/features/user/core/leads/import/imports-api.service.ts` | modified (small) — add pagination/filter params to `list()` and `downloadSource(id)` helper |
| `app/src/app/features/user/core/leads/leads.routes.ts` | modified — add `/import-history` route |
| `app/src/app/features/user/layout/sidebar.component.html` | modified — add menu entry |
| `api/src/app/core/leads/imports/router.py` | modified (small) — `GET /leads/import` supports `?page=&page_size=&status=&source_platform=` if not already in Step 1; also add `GET /{id}/source` to stream the original file (separate from the existing errors endpoint) |

**6 files (5 frontend + 1 small backend addendum).** Inside rule-8 budget.

## Plan

1. (Backend, small) Extend `GET /leads/import` with optional `page`, `page_size`, `status`, `source_platform` query params. Return `{items: [...], total: N, page, page_size}`. If Step 1 already shipped these, skip.
2. (Backend, small) Add `GET /leads/import/{id}/source` — streams the original uploaded file with the original filename in `Content-Disposition`. Permission-gated, RLS-checked. Mirrors the `/errors.csv` endpoint pattern.
3. Build `HistoryPageComponent`:
   - Signals for filters: `status = signal<Filter>('all')`, `sourcePlatform = signal<Filter>('all')`, `page = signal(1)`.
   - `effect()` refetches when any filter changes.
   - Renders Tailwind table; mobile collapse acceptable (each row stacks into a card on `<768px`).
4. Action menu: PrimeNG `Menu` or a simple Tailwind dropdown — match existing convention in other list pages.
5. Cancel action: confirm modal → POST `/cancel` → refetch.
6. Download actions: anchor with `download` attribute pointing at `/api/v1/leads/import/{id}/source` and `/errors.csv` respectively, with the bearer token via either a query param or a one-shot signed URL — match the existing project's pattern for authenticated downloads (likely a fetch-and-blob helper).
7. Sidebar entry + route wire-up.

## Tests

Manual smoke per checklist. No new unit tests.

## Smoke (browser)

```
1. Log in as Owner. Sidebar shows "Import history" under Leads.
2. Click it. Empty state if first import isn't run yet, otherwise the table
   with prior runs (continuing from Steps 4-5 smoke).
3. Filter to status=Completed. Table narrows.
4. Filter source platform to Zoho. Further narrows.
5. Click a row's kebab → "Download errors" → CSV downloads, contains the bad rows
   from Step 5's smoke.
6. Click "Download source" → original CSV downloads with the original filename.
7. Run a fresh import; pause on the result page during processing. In a second tab,
   open the history page → that row shows status "Processing". Click "Cancel" →
   confirm → status moves to "Cancelled". The first tab's polling reflects the change.
8. Paginate: with 25+ imports seeded, "Next page" works; counts update.
9. As Employee (no leads.import) → sidebar hides; direct visit → Access Denied.
```

## Risks

- **Source file download cost:** streaming a 10 MB file through FastAPI is fine, but if many concurrent downloads occur, consider a future move to signed-URL local-file serving via `FileResponse`. For v1, `StreamingResponse` is fine.
- **Status badge colour matrix proliferates:** keep it tight — gray for terminal-neutral (Awaiting mapping, Cancelled), blue for in-progress (Processing, Mapping committed), green for Completed, red for Failed. Reuse the colour helpers from the leads list badge if any.
- **Action menu cluttered:** four actions max per row. If more grow later, push to a detail page.

## Rollback

Delete the new component files. Revert the routes + sidebar edits. The list endpoint widening is additive; leave it or revert with the rest. Source-download endpoint can be removed safely (nothing else consumes it).
