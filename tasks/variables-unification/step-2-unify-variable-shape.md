# Step 2 — Unify `VariableDef` shape (fold `Variable` + `FieldSpec`)

**Goal:** collapse three data shapes (`VariableDef` in templates, `Variable` in chatbots, `FieldSpec` in automation) into ONE superset `VariableDef` in `core/variables/schemas.py`. Add adapter shims for the two legacy shapes so existing callers keep working during the transition.
**Phase:** Variables Unification track — step 2/13
**Depends on:** Step 1
**Status:** Pending

## Scope

**In-scope:**
- Extend `core/variables/schemas.VariableDef` to include all fields from the three existing shapes:
  - `path: str` (existing)
  - `label: str` (existing)
  - `type: Literal["string","int","currency","date","url","bool","email","phone","text"]` (from templates)
  - `group: str | None` (from automation `FieldSpec.group`)
  - `sample: str | None` (from chatbots)
  - `default: str | None` (existing — for insertion-time fallback)
  - `required: bool = False` (from templates)
  - `description: str | None` (from chatbots)
  - `help_text: str | None` (from automation)
  - `enum_resolver: str | None` (from automation — name of a resolver returning enum values, e.g. `pipeline_stages`)
  - `is_sensitive: bool = False` (NEW — gates on entity-read perm when true; standard fields default false)
  - `is_resolvable_here: bool = True` (NEW — populated by Step 5 depending on surface context)
- Add adapter functions:
  - `from_field_spec(fs: FieldSpec) -> VariableDef` in `core/automation/field_specs.py`
  - `from_chatbot_variable(v: Variable) -> VariableDef` in `core/chatbots/variables.py`
  - `to_field_spec(vd: VariableDef) -> FieldSpec` (reverse — for the `/event-types` view over shared catalog until Step 10b migrates it)
- Update existing `VariableGroup` dataclass in chatbots + `EventTypeSpec` in automation to accept `list[VariableDef]` (via adapter).

**Out of scope:**
- Endpoint changes (Step 4).
- Frontend consumption (Steps 7a/7b onwards).

## Files to touch
- `api/src/app/core/variables/schemas.py` (modified — extended shape).
- `api/src/app/core/automation/field_specs.py` (modified — add `from_field_spec` / `to_field_spec` bridge).
- `api/src/app/core/chatbots/variables.py` (modified — add `from_chatbot_variable` adapter; existing `Variable` dataclass kept for one release as compat).
- `api/src/app/core/templates/variables.py` (modified — internal `VariableDef` dataclass reference points to the new Pydantic model via adapter).
- Tests for the shape (new).

## Plan
1. Extend `VariableDef` schema with all superset fields; defaults preserve backward-compat.
2. Write adapters in the two legacy homes (automation + chatbots) — pure functions, no behavior change.
3. Update the three composition sites to use `VariableDef` internally, adapter to legacy shape at API boundary if needed:
   - Templates `/templates/variables/{channel}` (shim endpoint, retired in Step 11) — returns the templates shape (adapter converts).
   - Chatbots `/chatbots/variables` (shim endpoint, retired in Step 11) — returns the chatbots shape.
   - Automation `/automations/event-types` — returns automation's shape (kept as view over shared catalog per Step 10b).
4. Test round-trip for every existing caller shape.

## DB changes / migrations
None.

## Tests to add
- `test_variable_def_superset_has_all_fields_from_three_shapes`.
- `test_from_field_spec_preserves_all_fields`.
- `test_from_chatbot_variable_preserves_sample_and_description`.
- `test_to_field_spec_reverse_roundtrip_preserves_enum_resolver_and_help_text`.
- `test_templates_variables_endpoint_still_returns_legacy_shape` (backward-compat during transition).
- `test_chatbots_variables_endpoint_still_returns_legacy_shape`.
- `test_automation_event_types_endpoint_still_returns_legacy_shape`.

## Verification checklist
- Backend: all three legacy endpoints return byte-compatible responses (compare to snapshot).
- Backend: `uv run pytest api/tests/test_variables_shape.py -x` — new tests pass.
- Code review: `VariableDef` is a Pydantic v2 model, not a dataclass (Pydantic v2 spec requirement).
- No frontend changes.

## Self-check (10 rules)
- [ ] Rule 1: pure core.
- [ ] Rule 2: no DB changes.
- [ ] Rule 3: N/A.
- [ ] Rule 4: N/A.
- [ ] Rule 5: N/A.
- [ ] Rule 6: N/A.
- [ ] Rule 7: N/A.
- [ ] Rule 8: ~6 files — under limit.
- [ ] Rule 9: stop and report.
- [ ] Rule 10: adapters explicitly retire when Steps 8/9/10a/10b/11 land — deprecations.md tracks them.

## Stop & report
Use the master-prompt stop template; await "proceed".
