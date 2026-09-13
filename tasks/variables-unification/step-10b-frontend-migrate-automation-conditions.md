# Step 10b — Migrate Automation Conditions builder + `/event-types` becomes view over shared catalog

**Goal:** the automation Conditions builder consumes the shared `VariableRegistryService`. Backend `/automations/event-types` becomes a **view** — it composes `variables` from the shared catalog + adds `condition_fields` filter (which of those variables are filterable in conditions, via `FieldSpec.group=='filterable'`).
**Phase:** Variables Unification track — step 10b/13
**Depends on:** Step 10a
**Status:** Pending

## Scope

**In-scope:**
- Backend: `core/automation/service.list_event_types_with_custom_fields()` refactored — no longer batches `list_fields_by_entities` directly. Instead calls `core/variables/service.list_variables(entity, channel=None, event=<event_type>)` for each catalog event, then layers `condition_fields` (filterable subset) on top.
- Frontend: `APP/.../automation/conditions/*` — swap the private variable/field data source for `VariableRegistryService`.
- Preserve API contract of `/automations/event-types` byte-for-byte (existing saved conditions must round-trip). Adapter maps `VariableDef` → `FieldSpec` at boundary.

**Out of scope:**
- Retiring `/automations/event-types` (still needed for conditions builder's `condition_fields` extension).

## Files to touch
- `api/src/app/core/automation/service.py` (modified).
- `APP/src/app/features/user/core/automation/conditions/*.ts` (modified).
- Contract test.

## Plan
1. Backend refactor with byte-compat snapshot test.
2. Frontend swap.
3. Playwright regression on existing saved conditions.

## Tests to add
- Backend contract test: `/automations/event-types` response byte-identical pre/post refactor (fixture-based).
- Playwright: open existing automation with saved conditions, edit, save — no data loss.
- Playwright: create new condition on custom-event trigger (once Track B lands) → picker offers custom-event payload keys.

## Verification checklist
- Backend: contract test passes.
- Frontend: prettier + eslint clean.
- Manual: existing automation conditions still render + save correctly.

## Self-check
- [ ] Rules N/A / clean.
- [ ] Rule 8: 3 files.

## Stop & report
Await "proceed".
