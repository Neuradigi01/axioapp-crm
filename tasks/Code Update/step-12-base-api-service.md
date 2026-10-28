# Step 12 — `BaseApiService<T>`

**Goal:** Replace the 18 hand-rolled API services (`list / get / create / update / delete / bulkDelete / bulkReassign`) with one generic base class.
**Track:** Code Update — Frontend Foundation
**Depends on:** Step 11 (`buildHttpParams`)
**Status:** Not started

## Scope
**In-scope:**
- Create `app/src/app/features/user/core/shared/services/base-api.service.ts`:
  ```ts
  export abstract class BaseApiService<T, Q = unknown> {
    protected abstract readonly basePath: string;
    protected http = inject(HttpClient);
    list(query?: Q): Observable<PaginatedResponse<T>> { ... }
    get(id: string): Observable<T> { ... }
    create(payload: Partial<T>): Observable<T> { ... }
    update(id: string, payload: Partial<T>): Observable<T> { ... }
    delete(id: string): Observable<void> { ... }
    bulkDelete(ids: string[]): Observable<BulkResult> { ... }
    bulkReassign(ids: string[], assigneeId: string): Observable<BulkResult> { ... }
  }
  ```
- Migrate 18 services to subclass `BaseApiService`; keep domain-specific extras as additional methods.

**Out of scope:**
- Caching / SWR (separate concern).
- Optimistic updates.

## Files to touch
- `core/shared/services/base-api.service.ts` (create)
- `core/shared/services/base-api.service.spec.ts` (create)
- `core/shared/types/paginated-response.ts` (create — matches backend Step 1)
- `core/shared/types/bulk-result.ts` (create)
- All 18 `*-api.service.ts` files (slim down to override `basePath` + domain extras)

## Plan
1. Implement base service using `buildHttpParams` from Step 11.
2. Define matching TS types for `PaginatedResponse<T>` and `BulkResult`.
3. For each existing service:
   - Set `protected readonly basePath = '/api/v1/contacts';` etc.
   - Delete the boilerplate methods.
   - Keep entity-specific methods (e.g. `convertLead`, `markPaid`).
4. Confirm pages still compile — they consume the same observable signatures.

## DB changes / migrations
None.

## Tests to add
- Unit: base service issues correct HTTP verbs against `basePath`.
- Unit: bulk methods POST `{ids}`.
- Spec: subclass with `basePath = '/api/v1/contacts'` round-trips.

## Verification checklist
- `ng test` — green.
- `ng build` — clean.
- Browser smoke: CRUD a contact, lead, task end-to-end.

## Self-check (10 rules)
- [ ] 18 services now ~10-20 LOC each (was ~100-150).
- [ ] Domain-specific methods preserved.
- [ ] No old boilerplate left commented.

## Stop & report
Files changed · LOC removed · Tests added · "Awaiting your 'proceed'".
