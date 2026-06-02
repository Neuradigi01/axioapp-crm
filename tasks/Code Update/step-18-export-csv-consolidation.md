# Step 18 — Consolidate `exportCsv` param building

**Goal:** Eliminate the duplicate-and-strip pattern in `exportCsv()` methods (copies `list()` params then deletes pagination keys — drift-prone).
**Track:** Code Update — Frontend Polish
**Depends on:** Step 11 (`buildHttpParams`), Step 12 (`BaseApiService<T>`)
**Status:** Not started

## Scope
**In-scope:**
- Extend `BaseApiService<T>` with `exportCsv(query: Q): Observable<Blob>` that drops `page/pageSize` from the param set automatically.
- Migrate contacts and leads CSV-export methods.

**Out of scope:**
- Server-side export format changes.
- New entity exports (each subclass can opt in by setting `supportsExport = true`).

## Files to touch
- `core/shared/services/base-api.service.ts` (extend)
- `core/contacts/contacts-api.service.ts` (`:240-259` — delete)
- `core/leads/leads-api.service.ts` (`:169-180` — delete)

## Plan
1. Add `exportCsv()` to base, using `buildHttpParams({ ...query, page: undefined, pageSize: undefined })`.
2. Delete overrides in contacts / leads.
3. Browser smoke: export a filtered contacts CSV; confirm filter applied, no pagination keys in query string.

## DB changes / migrations
None.

## Tests to add
- Spec: `exportCsv()` query string omits `page` / `pageSize`.

## Verification checklist
- DevTools network: export request shows correct query string.

## Self-check (10 rules)
- [ ] No two places define export-param-building logic.

## Stop & report
Files changed · LOC removed · "Awaiting your 'proceed'".
