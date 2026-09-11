# Step 10a — Migrate Chatbots editor to shared picker (data-source swap)

**Goal:** point the chatbots builder at the shared `VariableRegistryService` (endpoint `/api/v1/variables?entity=chatbot_runtime&channel=chatbot`) instead of its own `/chatbots/variables`. Add "not resolvable here" badge on paths where `is_resolvable_here=false`. Retire `core/chatbots/variables.py` `list_variables()`.
**Phase:** Variables Unification track — step 10a/13
**Depends on:** Steps 7a, 7b
**Status:** Pending

## Scope

**In-scope:**
- Chatbots builder consumes `VariableRegistryService` via shared component (already the same file per Step 7a rename).
- `entity` set to `chatbot_runtime` for palette; `channel` = `chatbot`.
- "Not resolvable here" amber badge rendered when `is_resolvable_here=false` (chatbot won't resolve `lead.*` at runtime today).
- Retire endpoint `/chatbots/variables` (shim only until Step 11).
- Retire `core/chatbots/variables.py list_variables()` (Step 11).

**Out of scope:**
- Chatbot runtime resolver coverage for `lead.*` (follow-up `chatbot-runtime-resolver-coverage` track).

## Files to touch
- `APP/src/app/features/user/core/chatbots/builder/*.ts` (modified — swap data source).
- `APP/src/app/features/user/core/shared/variable-picker/variable-picker-api.service.ts` (modified — becomes re-export shim per Step 7b).
- `api/src/app/core/chatbots/router.py` (modified — `/chatbots/variables` becomes proxy to `/variables?entity=chatbot_runtime`).

## Plan
1. Chatbots builder swaps to shared registry.
2. Add badge rendering.
3. Endpoint proxy for one release.

## Tests to add
- Playwright: chatbots builder palette still opens; palette shows same variables + badge on `lead.*`.
- Playwright: insertion still works into Ask/Send/Save nodes.
- Backend: `/chatbots/variables` proxy returns identical payload.

## Verification checklist
- Frontend: prettier + eslint clean.
- Frontend: no chatbot regression.
- Backend: proxy test passes.

## Self-check
- [ ] Rules N/A / clean.
- [ ] Rule 8: 3 files.

## Stop & report
Await "proceed".
