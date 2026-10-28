# Step 5 — `TimestampedOrgScopedOut` mixin

**Goal:** Stop redefining `org_id: UUID`, `created_at: datetime`, `updated_at: datetime` in 98 output schemas — pull them into a shared mixin.
**Track:** Code Update — Foundations
**Depends on:** Step 4 (`ORMModel` in place)
**Status:** Not started

## Scope
**In-scope:**
- Add `TimestampedOrgScopedOut(ORMModel)` to `app/shared/schemas/base.py` with the three fields.
- Migrate every output schema that currently declares all three.

**Out of scope:**
- Optional `created_by` / `updated_by` (separate audit step if needed).
- Schemas that intentionally omit `org_id` (none in core today — verify).

## Files to touch
- `api/src/app/shared/schemas/base.py` (extend)
- Every output schema in `app/core/` and `app/packs/furniture/` that currently declares the three fields.

## Plan
1. Define `class TimestampedOrgScopedOut(ORMM

odel): org_id: UUID; created_at: datetime; updated_at: datetime`.
2. Grep for `org_id: uuid\.UUID` in `schemas.py` files → 98 hits. For each output schema that declares all three:
   - Change parent class to `TimestampedOrgScopedOut`.
   - Delete the three field declarations.
3. Confirm Pydantic field ordering still satisfies any positional model usage (unlikely; everything is kwargs).

## DB changes / migrations
None.

## Tests to add
- Unit: `TimestampedOrgScopedOut.model_validate(<row>)` round-trips correctly.
- Existing schema tests pass.

## Verification checklist
- `uv run pytest` — green.
- Swagger — every list/detail response still includes `org_id / created_at / updated_at`.
- Browser smoke: any detail page renders with timestamps.

## Self-check (10 rules)
- [ ] No commented-out field declarations.
- [ ] `org_id` is still required on every output (rule 2 cosmetic mirror).

## Stop & report
Files changed · LOC removed · "Awaiting your 'proceed'".
