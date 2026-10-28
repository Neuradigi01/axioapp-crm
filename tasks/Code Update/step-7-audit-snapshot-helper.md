# Step 7 — Generic `_snapshot` helper

**Goal:** Replace 7 hand-rolled `_snapshot(entity) -> dict` functions with a generic helper that serializes entity fields uniformly.
**Track:** Code Update — Audit & Validation
**Depends on:** Step 6 (wrapper exists; snapshots flow through it)
**Status:** Not started

## Scope
**In-scope:**
- Create `api/src/app/shared/audit/snapshots.py::snapshot(entity, *, exclude=None)` that uses SQLAlchemy column introspection to build a JSON-safe dict (id, dates, org_id, custom_data, scalar columns).
- Migrate the 7 known `_snapshot()` helpers.
- Entities with sensitive fields (e.g. password hashes — should not occur in CRM entities, but verify) use `exclude={"col1", ...}`.

**Out of scope:**
- Nested relationship serialization — keep flat (audit snapshots should be compact).
- Diffing logic (`before` vs `after` change detection).

## Files to touch
- `api/src/app/shared/audit/snapshots.py` (create)
- `api/src/app/core/contacts/service.py` (`:49-65`)
- `api/src/app/core/leads/service.py` (`:96-118`)
- `api/src/app/core/appointments/service.py` (`:67-79`)
- `api/src/app/core/catalog/service.py`
- `api/src/app/core/campaigns/service.py`
- `api/src/app/core/tasks/service.py`
- `api/src/app/core/walk_ins/service.py`
- `api/tests/shared/test_audit_snapshot.py` (create)

## Plan
1. Implement helper using `sqlalchemy.inspect(entity).mapper.column_attrs` to iterate scalar columns.
2. Serialize `UUID`/`datetime`/`Decimal` to strings; pass JSONB columns through.
3. Replace each `_snapshot(entity)` call site to import the shared helper.
4. Confirm audit event payloads remain bit-identical for representative entities (snapshot diff test in `tests/shared/test_audit_snapshot.py`).

## DB changes / migrations
None.

## Tests to add
- Unit: snapshot of a Contact row matches expected dict shape.
- Unit: `exclude` removes named fields.
- Integration: create one Lead → audit `after` dict is identical to pre-refactor.

## Verification checklist
- `uv run pytest` — green.
- Browser smoke: trigger updates for 3 different entity types; audit log entries look correct.

## Self-check (10 rules)
- [ ] No commented-out `_snapshot` functions.
- [ ] Snapshot output is JSON-safe (UUID → str, datetime → ISO).

## Stop & report
Files changed · LOC removed · Tests added · "Awaiting your 'proceed'".
