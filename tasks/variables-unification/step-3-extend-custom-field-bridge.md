# Step 3 — Extend `custom_field_bridge` + require `org_id` on `list_fields_by_entities`

**Goal:** eliminate duplicated custom-field composition (chatbots `_custom_field_variables`, automation `list_event_types_with_custom_fields`) by extending `custom_field_bridge.to_field_spec`. Make `org_id` a REQUIRED kwarg on `list_fields_by_entities` — belt-and-suspenders enforced by type checker.
**Phase:** Variables Unification track — step 3/13
**Depends on:** Step 1, Step 2
**Status:** Pending

## Scope

**In-scope:**
- `core/custom_fields/data_access.list_fields_by_entities(org_id: UUID, entity_types: list[str], include_hidden: bool = False)` — `org_id` becomes a required, non-defaulted kwarg. Type checker will fail every existing caller that omits it.
- `core/custom_fields/data_access.py` — add explicit `WHERE tbl_custom_field_definitions.org_id = ?` to the query (belt); RLS remains (suspenders).
- Audit and update every existing caller:
  - `core/automation/service.list_event_types_with_custom_fields` (pass `org_id` from `TenantContext`).
  - `core/automation/custom_field_bridge.mounts_for` / `all_mounted_entity_types` (same).
  - `core/chatbots/variables._custom_field_variables` (already uses `list_visible_custom_fields_for_org` which has explicit `org_id` — no change; kept for one release, deleted in Step 10a).
  - Any test fixtures.
- Extend `custom_field_bridge.to_field_spec` — accepts an optional `is_sensitive` flag (from `tbl_custom_field_definitions.is_sensitive`, added below).
- Add column `tbl_custom_field_definitions.is_sensitive BOOLEAN DEFAULT FALSE` (migration). Standard fields have no is_sensitive concept; only custom fields.

**Out of scope:**
- Provider registry (Step 4 — inside `core/variables/service.py`).
- Endpoint (Step 4).

## Files to touch
- `api/src/app/core/custom_fields/data_access.py` (modified — required `org_id` kwarg, explicit WHERE).
- `api/src/app/core/custom_fields/models.py` (modified — add `is_sensitive` column).
- `api/src/app/core/automation/custom_field_bridge.py` (modified — accept `is_sensitive` in `to_field_spec`).
- `api/src/app/core/automation/service.py` (modified — pass `org_id` to `list_fields_by_entities`).
- `api/alembic/versions/NNNN_custom_field_is_sensitive.py` (new migration; ≤32 char revision ID per memory).
- Tests.

## Plan
1. Migration: add `is_sensitive BOOLEAN NOT NULL DEFAULT FALSE` to `tbl_custom_field_definitions`. Up + down.
2. Update `CustomFieldDefinition` model.
3. Change `list_fields_by_entities` signature: `org_id: UUID` is required. Add explicit `.where(CustomFieldDefinition.org_id == org_id)` predicate.
4. Grep every caller of `list_fields_by_entities`; add `org_id` param — should be trivial (they all have `TenantContext.org_id` available or accept `org_id` themselves).
5. Extend `to_field_spec` to propagate `is_sensitive`.
6. Add regression test that patches out RLS (`SET row_security = off`) and asserts cross-tenant read still returns empty (belt-only path).

## DB changes / migrations
```sql
-- Up
ALTER TABLE tbl_custom_field_definitions
  ADD COLUMN is_sensitive BOOLEAN NOT NULL DEFAULT FALSE;

-- Down
ALTER TABLE tbl_custom_field_definitions DROP COLUMN is_sensitive;
```

## Tests to add
- `test_list_fields_by_entities_requires_org_id_kwarg` — call without `org_id` → TypeError from type-checker + runtime.
- `test_list_fields_by_entities_explicit_org_id_filter_blocks_cross_tenant_with_rls_disabled` — patch RLS off, insert cross-tenant field, query returns empty.
- `test_custom_field_is_sensitive_column_default_false`.
- `test_to_field_spec_propagates_is_sensitive`.

## Verification checklist
- Backend: `uv run pytest api/tests/test_custom_fields_dal.py -x` passes.
- Backend: `uv run pytest api/tests/test_automation_service.py -x` passes.
- Backend: migration up + down clean.
- Code review: type-checker fails on any caller that omits `org_id`.
- Frontend: no changes.

## Self-check (10 rules)
- [ ] Rule 1: pure core.
- [ ] Rule 2: `tbl_custom_field_definitions` already has `org_id` + RLS; new column doesn't touch that.
- [ ] Rule 3: consumes; extends metadata additively.
- [ ] Rule 4: N/A.
- [ ] Rule 5: N/A.
- [ ] Rule 6: N/A.
- [ ] Rule 7: N/A.
- [ ] Rule 8: ~5 files — under limit.
- [ ] Rule 9: stop and report.
- [ ] Rule 10: no TODOs; deprecations tracked.

## Stop & report
Use master-prompt stop template; await "proceed".
