# Step 11 — `buildHttpParams` utility

**Goal:** Replace the conditional `if (query.x) params = params.set(...)` chain duplicated in 18 Angular API services with one utility.
**Track:** Code Update — Frontend Foundation
**Depends on:** none
**Status:** Not started

## Scope
**In-scope:**
- Create `app/src/app/features/user/core/shared/services/query-builder.ts::buildHttpParams(query: Record<string, unknown>): HttpParams`.
- Skip `undefined`/`null`/`''` keys; serialize arrays as repeated keys; stringify numbers and booleans.
- Migrate the 18 API services.

**Out of scope:**
- Server-side parsing changes (FastAPI handles repeated query params already).
- Re-naming any service method.

## Files to touch
- `app/src/app/features/user/core/shared/services/query-builder.ts` (create)
- `app/src/app/features/user/core/shared/services/query-builder.spec.ts` (create)
- `core/contacts/contacts-api.service.ts` (`:146-165, 240-259`)
- `core/leads/leads-api.service.ts` (`:292-323`)
- `core/tasks/tasks-api.service.ts` (`:77-90`)
- `core/walk-ins/walk-ins-api.service.ts` (`:83-94`)
- `core/appointments/appointments-api.service.ts`
- `core/catalog/catalog-api.service.ts`
- Remaining 12 `*-api.service.ts` files

## Plan
1. Implement utility: iterate entries, skip empty values, append or set on `HttpParams`.
2. Grep for `let params = new HttpParams\(\)` → 18+ hits.
3. Replace each builder block with `const params = buildHttpParams({ q: query.q, page: query.page, ... });`.
4. Confirm CSV export endpoints (which inherit query-building) still produce identical query strings.

## DB changes / migrations
None.

## Tests to add
- Unit (jasmine): skip undefined, serialize array, stringify numbers/booleans.
- Smoke: open Contacts list with filters applied → network request shows correct query string.

## Verification checklist
- `ng test` — green.
- `ng build` — clean.
- Browser smoke: search + filter + paginate Contacts in Ajay's Workspace.

## Self-check (10 rules)
- [ ] Old builder blocks deleted.
- [ ] No service kept its own `if (x) params.set(...)` chain.

## Stop & report
Files changed · LOC removed · Tests added · "Awaiting your 'proceed'".
