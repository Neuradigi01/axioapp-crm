# Step 11 — Cleanup: name-based CI pin-test + deprecation calendar + smoke

**Goal:** close the track: retire the three shim endpoints/services, add a name-based pin-test that bans variable-picker components outside `shared/variable-picker/`, publish the deprecation calendar with concrete removal-target dates, run the Ajay's Workspace smoke.
**Phase:** Variables Unification track — step 11/13
**Depends on:** all prior steps
**Status:** Pending

## Scope

**In-scope:**
- Delete shims scheduled for retirement:
  - `core/templates/variables.py` (re-export shim from Step 1) — direct callers all migrated.
  - `core/chatbots/variables.py list_variables()` — chatbots builder now uses shared registry.
  - `/templates/variables/{channel}` endpoint — TemplatesApiService.variables() rewired to `/variables`.
  - `/chatbots/variables` endpoint — Chatbots api-service rewired.
  - `variable-picker-api.service.ts` re-export shim.
- CI pin-test `api/tests/test_shared_variable_picker_only.py` — asserts:
  1. Only ONE `*variable-picker*.component.ts` exists under `APP/src/app/features/user/core/` and it lives in `shared/variable-picker/`.
  2. No file under `APP/src/app/features/user/core/**/` imports `HttpClient` and defines `path: '...'` + `label: '...'` inline more than 3 times outside `shared/variable-picker/`.
- `tasks/variables-unification/deprecations.md` — concrete removal target dates (e.g. `2026-11-15`), owner (Neuradigi01), telemetry-based guard (14 days zero non-first-party calls in access logs).
- Ajay's Workspace smoke: org `41f9ede9-41b3-44ce-b489-3004566d4068`, Owner `ajaygogane224@gmail.com` (per project memory). Manual walk-through: Templates + Workflows + Chatbots + Automation Conditions builders — variables inserted successfully across each.

**Out of scope:**
- Custom-events-specific tests (Track B).

## Files to touch
- Deletions: 3 shim files + 2 endpoint routes.
- New: `api/tests/test_shared_variable_picker_only.py`.
- New: `tasks/variables-unification/deprecations.md`.
- Modified: `main.py` router includes.
- Modified: `TemplatesApiService`, chatbots API service (rewire to `/variables`).

## Plan
1. Delete each shim (in dependency order — endpoints first, then services, then re-export shim).
2. Add pin-test.
3. Publish deprecations.md.
4. Run smoke.

## Tests to add
- `test_shared_variable_picker_only` (pin-test).
- Smoke test document with pass/fail per surface.

## Verification checklist
- Backend: `uv run pytest api/tests/test_shared_variable_picker_only.py -x` passes.
- Backend: no residual imports of retired paths.
- Frontend: manual smoke — all 4 surfaces work.
- Playwright: previously written tests all still pass.

## Self-check
- [ ] Rules N/A / clean.
- [ ] Rule 10: shims fully deleted here — no lingering half-done.

## Stop & report
Track complete. Final report per master template.
