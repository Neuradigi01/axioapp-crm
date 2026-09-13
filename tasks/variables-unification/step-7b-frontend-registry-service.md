# Step 7b — `VariableRegistryService` (cache + org.switched + BroadcastChannel)

**Goal:** replace chatbots' private `variable-picker-api.service.ts` with a shared `VariableRegistryService` that fetches `/api/v1/variables`. Cache keyed by `(org_id, user_permission_hash, entity, channel, event)`; invalidated via `custom-field-mutated` same-tab bus, `BroadcastChannel` cross-tab (opaque payload only), `org.switched` on org-switcher, `role.changed` on permission mutation.
**Phase:** Variables Unification track — step 7b/13
**Depends on:** Step 7a
**Status:** Pending

## Scope

**In-scope:**
- `APP/src/app/features/user/core/shared/variable-picker/variable-registry.service.ts` (new — supersedes `variable-picker-api.service.ts`; that file becomes a re-export shim, deleted in Step 11 per deprecations).
- `shareReplay(1)` cache keyed by `(org_id, user_permission_hash, entity, channel, event)`. TTL 5 min from last-access.
- `user_permission_hash` computed from the current user's permission list (SHA-1 of sorted perm strings); invalidates when Owner mutates the user's role.
- Bus subscribers:
  - `custom-field-mutated` (existing bus signal) → clear cache for entity in payload.
  - `custom-field-renamed` / `custom-field-type-changed` (new) → same.
  - `org.switched` (find existing signal in `SessionService` or add if missing) → clear entire cache.
  - `role.changed` (find existing) → recompute `user_permission_hash`, clear entire cache.
- `BroadcastChannel('crm-variable-registry')` — same-browser cross-tab invalidation. **Payload is opaque `{ org_id, generation }` — NEVER field paths or labels.** Receiver bumps its cache generation if `org_id` matches its current session.
- Fallback for browsers without `BroadcastChannel` (Safari private, older browsers): TTL-only (documented in service JSDoc + a `console.info` at construction if unavailable).
- ETag-conditional fetching (send `If-None-Match` header from cache).

**Out of scope:**
- Surface migrations (Steps 8-10).
- HTTP retry interceptor (already exists per project memory — new endpoints inherit).

## Files to touch
- `APP/src/app/features/user/core/shared/variable-picker/variable-registry.service.ts` (new).
- `APP/src/app/features/user/core/shared/variable-picker/variable-picker-api.service.ts` (modified — re-export shim; scheduled for deletion in Step 11).
- `APP/src/app/features/user/core/shared/session/session.service.ts` (modified — emit `org.switched` if not present).
- `APP/src/app/features/user/core/shared/session/permissions.service.ts` (modified — emit `role.changed` if not present).
- Tests.

## Plan
1. Implement `VariableRegistryService` with signals-based cache + BroadcastChannel.
2. Wire bus subscribers (org, role, custom-field mutations).
3. Add ETag-conditional fetch (uses HttpClient interceptor if standard, else inline).
4. Retire private chatbots service (shim only).
5. Tests: cache hit/miss/TTL/org-switch invalidation/BroadcastChannel opacity.

## DB changes / migrations
None.

## Tests to add
- Service spec: caches by (org_id, user_permission_hash, entity, channel, event).
- Service spec: org.switched clears cache.
- Service spec: role.changed recomputes hash + clears cache.
- Service spec: BroadcastChannel payload is `{org_id, generation}` — no paths.
- Service spec: cross-org BroadcastChannel event ignored (org_id mismatch).
- Playwright: two tabs same org, custom-field added in tab 1, tab 2 refetches within 1s.
- Playwright: org-switch clears picker.

## Verification checklist
- Frontend: unit tests pass.
- Frontend: BroadcastChannel opacity verified by DevTools listener.
- Frontend: prettier + eslint clean.

## Self-check
- [ ] Rule 1-10: as per Step 7a.
- [ ] Rule 8: 4 files.

## Stop & report
Await "proceed".
