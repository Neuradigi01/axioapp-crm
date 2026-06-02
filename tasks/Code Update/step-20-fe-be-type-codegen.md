# Step 20 — FE ↔ BE type codegen

**Goal:** Stop hand-maintaining TS interfaces that mirror Pydantic schemas. Generate them automatically so backend schema changes can't silently drift from frontend types.
**Track:** Code Update — Cross-cutting
**Depends on:** Step 12 (`BaseApiService<T>` — FE shape is stable enough to bind to generated types)
**Status:** Not started

## Scope
**In-scope:**
- Pick **one** of two approaches:
  - **Option A** — `openapi-typescript`: backend already exposes `/openapi.json`; add `npm run generate:api-types` that runs `openapi-typescript http://localhost:8000/openapi.json -o app/src/app/features/user/core/shared/api-types/index.ts`.
  - **Option B** — custom Pydantic → TS generator (more control, more code to own).
- Replace hand-written types: `ContactListItem`, `Lead`, `TaskListFilters`, custom-field types, response envelopes.
- Document in repo root README how to regenerate.

**Out of scope:**
- Generated Angular client (we keep `BaseApiService<T>`).
- Generating into `staff-portal/` (separate scope).

## Files to touch
- `app/package.json` (add dev dep + script)
- `app/src/app/features/user/core/shared/api-types/index.ts` (generated; git-tracked)
- Every FE file currently importing a hand-rolled interface — switch import path.
- `README.md` or `docs/codegen.md` (one paragraph + command).

## Plan
1. Decide A vs B. Recommend Option A for first pass — lowest effort, off-the-shelf.
2. Add script + run it; commit generated file.
3. Migrate ~10 highest-traffic interfaces first (Contact, Lead, Task, Walk-in, Appointment, custom-field defs).
4. Add a CI check (or pre-commit hook later) that regenerates and fails on diff.
5. Decide policy: regenerate per backend PR or per FE PR — document.

## DB changes / migrations
None.

## Tests to add
- CI step: regenerate types; assert `git diff --exit-code` on the generated file.

## Verification checklist
- `npm run generate:api-types` runs clean against a running backend.
- TS compile error if a backend field is removed without regenerating.

## Self-check (10 rules)
- [ ] Generated file marked with header `// AUTO-GENERATED — do not edit by hand`.
- [ ] At least one FE consumer migrated to prove the loop closes.

## Stop & report
Files changed · interfaces replaced · doc updated · "Awaiting your 'proceed'".
