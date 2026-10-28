# Step 4 — `ORMModel` base Pydantic class

**Goal:** Replace `model_config = ConfigDict(from_attributes=True)` repeated 53 times across output schemas with one shared base class.
**Track:** Code Update — Foundations
**Depends on:** none
**Status:** Not started

## Scope
**In-scope:**
- Create `api/src/app/shared/schemas/base.py::ORMModel(BaseModel)` with pre-configured `ConfigDict(from_attributes=True)`.
- Migrate every output schema in `app/core/` and `app/packs/furniture/` to inherit from `ORMModel` instead of `BaseModel`.

**Out of scope:**
- Input/request schemas (those don't need `from_attributes`).
- Re-arranging schema files.

## Files to touch
- `api/src/app/shared/schemas/base.py` (create)
- Every `schemas.py` under `app/core/` (~20 files) — swap `BaseModel` → `ORMModel` on output classes; remove duplicated `model_config` line.
- Same under `app/packs/furniture/modules/*/schemas.py`.

## Plan
1. Create `ORMModel` with `model_config = ConfigDict(from_attributes=True, populate_by_name=True)`.
2. Grep `ConfigDict\(from_attributes=True\)` → 53 hits. For each:
   - Replace `class X(BaseModel):` → `class X(ORMModel):`.
   - Delete the `model_config = ConfigDict(...)` line.
3. Confirm no schema relied on a different `ConfigDict` value (e.g. `extra="forbid"`); if so, keep it explicit on that class.

## DB changes / migrations
None.

## Tests to add
- Unit: `ORMModel.model_validate(<sqlalchemy row>)` works.
- Existing schema tests pass unchanged.

## Verification checklist
- `uv run pytest` — green.
- Swagger `/docs` — schemas unchanged.
- Browser smoke: open Contacts detail → fields render correctly.

## Self-check (10 rules)
- [ ] No commented-out `model_config` lines.
- [ ] Output schemas now inherit `ORMModel`; request schemas still inherit `BaseModel`.

## Stop & report
Files changed · LOC removed · Tests added · "Awaiting your 'proceed'".
