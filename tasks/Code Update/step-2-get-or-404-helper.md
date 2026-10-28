# Step 2 — `get_or_404` helper

**Goal:** Replace 15+ inlined `if row is None: raise HTTPException(404, ...)` blocks with a single shared `get_or_404(session, model, id, *, entity_name)` helper.
**Track:** Code Update — Foundations
**Depends on:** none
**Status:** Not started

## Scope
**In-scope:**
- Create `api/src/app/shared/db/queries.py::get_or_404(session, model, id, *, org_id, entity_name)`.
- Helper signature enforces `org_id` filter (rule 2 — every query is org-scoped).
- Migrate the 15+ known call sites in `app/core/` and `app/packs/furniture/`.

**Out of scope:**
- Cross-tenant admin-mode lookups (not used yet).
- Eager-loading variants (callers that need `selectinload` keep their own query).

## Files to touch
- `api/src/app/shared/db/__init__.py` (create)
- `api/src/app/shared/db/queries.py` (create)
- `api/src/app/core/contacts/service.py` (replace at `:258-262`)
- `api/src/app/core/leads/service.py` (`:362-366`)
- `api/src/app/core/appointments/service.py` (`:362-367`)
- `api/src/app/packs/furniture/modules/inventory/service.py` (`:71-74`)
- `api/src/app/packs/furniture/modules/custom_orders/service.py` (`:93-97`)
- `api/src/app/core/{calls,campaigns,catalog,conversations,billing,walk_ins,tasks,reviews}/service.py`
- `api/tests/shared/test_get_or_404.py` (create)

## Plan
1. Implement the helper: build `select(model).where(model.id == id, model.org_id == org_id)`, run, raise `HTTPException(404, detail=f"{entity_name} not found")` on `None`.
2. Grep for `if .+ is None:\s*\n\s*raise HTTPException\(.*404` to find all call sites.
3. Replace each. Keep call site type-annotated so `mypy --strict` (if used) stays clean.
4. Confirm no service swallows the 404 silently elsewhere.

## DB changes / migrations
None.

## Tests to add
- Unit test: helper returns row when present.
- Unit test: helper raises 404 with correct detail when row missing.
- Unit test: helper raises 404 when row exists but `org_id` mismatches (tenant isolation).

## Verification checklist
- `uv run pytest tests/shared/test_get_or_404.py` — green.
- Browser smoke: fetch a contact that doesn't exist → 404 with the new message format.

## Self-check (10 rules)
- [ ] Helper enforces `org_id` filter — no way to bypass tenant scoping.
- [ ] No `/core` → `/packs` imports.
- [ ] Old inlined blocks removed (not commented out).

## Stop & report
Files changed · LOC removed · Tests added · "Awaiting your 'proceed'".
