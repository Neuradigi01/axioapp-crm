# Step 5 — Frontend: column-mapping UI + preview

**Goal:** Build `/user/leads/import/:id/mapping` — for an `awaiting_mapping` import, show every CSV column on the left, a dropdown of CRM targets on the right, pre-filled from the platform's system preset, plus a preview of the first 5 rows as they would land. User can save the mapping as a named org preset, then click Commit to enqueue the import job.
**Track:** Bulk Import
**Status:** Pending
**Depends on:** Step 4 (upload page), Steps 1–3 (backend including `GET /import/{id}/preview` and `GET /import/targets` and presets API).

---

## Scope

In-scope:

- New endpoint dependency: `GET /api/v1/leads/import/{id}/preview?limit=5` returning the first N rows as `{columns: ["Full Name",...], rows: [["Asha","asha@…"],...]}`. **Add this endpoint to Step 2 in passing if missed — small enough to fold in.**
- `MappingPageComponent` route at `/user/leads/import/:id/mapping`.
- Resolver/init: fetches `LeadImport`, `targets`, `presets` for the import's `source_platform`, and `preview`. Pre-fills mapping from the platform's system preset by best-match on column name (case-insensitive substring).
- For each CSV column row:
  - Left: column name + sample value from row 1.
  - Right: target dropdown (`-- Ignore --`, plus all targets grouped by `Standard lead | Standard contact | Custom fields`).
  - Marker icons:
    - Yellow if unmapped.
    - Red if mapped to a backend-required field that is missing (e.g. `contact.full_name`).
    - Green if mapped and valid.
- Preview pane (below the mapping table) showing 5 rows rendered as `{lead.title, contact.full_name, contact.phone, …}`. Updates reactively when mapping changes.
- Action bar:
  - "Save as preset" — opens a name prompt, calls `POST /presets`.
  - "Cancel import" — calls `POST /import/{id}/cancel`, returns to leads page.
  - "Commit" — disabled until all required fields mapped. Calls `POST /import/{id}/commit`, then routes to `/user/leads/import/{id}/result`.
- Result page (`/user/leads/import/:id/result`) — polls `GET /import/{id}` every 2s while status is `mapping_committed` or `processing`. On `completed`, shows the counts card + a "Download error report" button (if errors > 0) + a "Back to leads" CTA.

Out of scope:

- No column-reorder, no transform DSL (`UPPER(col)`, `concat(a,b)`).
- No incremental commit (preview-after-import). Single shot.
- No mobile-optimised layout — mapping screens on a phone don't make sense; show a "use a desktop" notice on viewports < 768px.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/leads/import/mapping-page.component.ts` | created |
| `app/src/app/features/user/core/leads/import/mapping-page.component.html` | created |
| `app/src/app/features/user/core/leads/import/mapping-row.component.ts` | created — per-column row |
| `app/src/app/features/user/core/leads/import/result-page.component.ts` | created |
| `app/src/app/features/user/core/leads/import/result-page.component.html` | created |
| `app/src/app/features/user/core/leads/import/imports-api.service.ts` | modified — add `preview()`, `commit()`, `cancel()`, `getPresets()`, `savePreset()` if not yet present |
| `api/src/app/core/leads/imports/router.py` | modified (small) — add `GET /{id}/preview?limit=N` if not added in Step 2 |

**7 files (6 frontend + 1 small backend addendum).** At rule-8 boundary; mapping UI is the central artifact of the track, so worth landing together. If implementation diff drifts above ~400 LOC, split mapping-page + result-page into 5a/5b.

## Plan

1. (If needed) Add the `/preview` endpoint to the backend. Reuses `parser.parse_rows()` to read the first N rows. Returns `{columns, rows}`.
2. Generate `MappingPageComponent` with a resolver that loads everything in parallel via `forkJoin` (or signals + `effect`):
   - `loadImport(id)` → the import row (must be `awaiting_mapping`; else redirect to result page).
   - `loadTargets()` → mappable CRM fields.
   - `loadPresets(sourcePlatform)` → system + org-owned presets.
   - `loadPreview(id)` → first 5 rows.
3. Build the auto-mapping function: for each CSV column, find the best-match target by:
   - Exact match on lowercased column name vs `target.label.toLowerCase()` or `target.key`.
   - Then substring match.
   - Else `null` (ignore).
   Source preset overrides this if present.
4. Render the mapping table with `@for (col of columns; track col)`. Each row is a `<app-mapping-row>` taking inputs `column`, `samples`, `targets`, `currentMapping`, and emitting `mappingChange`.
5. Required-field marker logic: read `target.backend_required`. If any backend-required target is not yet mapped to some column, surface a yellow banner above Commit.
6. Preview pane: a small Tailwind-styled card grid showing each preview row as `(lead) | (contact.full_name) | (contact.phone)`. Errors per cell highlighted red if Pydantic validation would fail (this is best-effort client-side; the server is the source of truth).
7. Commit handler: POST mapping → navigate to result.
8. Result page: signal-driven polling with `interval(2000)`. Stops polling on terminal statuses. Renders the counts card + downloads.

## Tests

Manual smoke per checklist. No new unit tests.

## Smoke (browser)

```
1. Continuing from Step 4: arrive on /user/leads/import/<id>/mapping.
2. CSV's 12 columns are listed. The Zoho preset has pre-filled 8 of them
   (Email → contact.email, Phone → contact.phone, etc.). 4 are still "-- Ignore --".
3. Yellow banner: "Required field 'contact.full_name' is not mapped."
4. Change "Lead Name" dropdown from Ignore to contact.full_name. Banner disappears.
   Green check appears on that row.
5. Preview pane updates: row 1 now shows {full_name: "Asha Reddy", email: "...", phone: "..."}.
6. Click "Save as preset". Name it "Zoho with full_name". Modal closes; preset persists
   (verify via /user/leads/import → next upload at Zoho source shows the new preset
   as the default).
7. Click Commit. Route changes to /user/leads/import/<id>/result.
   Spinner. Within ~2-5s, completes. Counts card shows
   "957 imported · 32 duplicates skipped · 11 errors".
8. Click "Download error report" → CSV downloads with the 11 bad rows + reasons.
9. Click "Back to leads" → /user/leads shows the new rows with green "Bulk import" badges.
10. Try opening /user/leads/import/<COMPLETED-id>/mapping → page detects the
    status mismatch and redirects to the result page for that import.
11. As Employee, direct visit to /user/leads/import/<id>/mapping → Access Denied.
```

## Risks

- **Auto-mapping false positives:** the substring-match heuristic could map "Email Address" to the wrong CRM field if the CRM has both `contact.email` and `contact.alt_email`. Surface mappings clearly; user can override every row. Document the heuristic's limitations in inline help on the mapping page (one short sentence).
- **Preview pane diverges from real validation:** client-side preview can only do basic shape checks; some backend validators (uniqueness, FK existence) need the server. Acceptable — preview is a hint, the server's error CSV is truth.
- **Polling load on the result page:** 2s interval is fine for small imports; for a 50k-row import that takes ~30s, 15 round-trips is negligible. If a user opens the page after the import completes, polling stops immediately (status already terminal).
- **Mapping JSON size:** a 100-column spreadsheet = 100-entry dict, well under any payload cap.

## Rollback

Delete the new files. Revert the imports-api service additions. The placeholder added in Step 4 can return.
