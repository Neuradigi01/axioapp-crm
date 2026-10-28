# Step 1 — Generic `PaginatedResponse[T]` schema

**Goal:** Replace the 16+ hand-rolled list-response classes (`items / total / page / size`) with one generic `PaginatedResponse[T]` in `app/shared/schemas/`.
**Track:** Code Update — Foundations
**Depends on:** none
**Status:** Not started

## Scope
**In-scope:**
- Create `api/src/app/shared/schemas/pagination.py` exposing `PaginatedResponse[T](BaseModel, Generic[T])` with fields `items: list[T]`, `total: int`, `page: int`, `size: int`.
- Migrate every existing list-response class in `app/core/` to use the generic.
- Update every `response_model=...` in routers to use `PaginatedResponse[ItemSchema]`.

**Out of scope:**
- `app/packs/furniture/` list responses (separate step if needed — most packs reuse core).
- Cursor-based pagination (offset-only here; matches what exists).

## Files to touch
- `api/src/app/shared/schemas/__init__.py` (create)
- `api/src/app/shared/schemas/pagination.py` (create)
- `api/src/app/core/contacts/schemas.py` (replace `ContactListResponse`)
- `api/src/app/core/leads/schemas.py` (replace `LeadListResponse`)
- `api/src/app/core/tasks/schemas.py` (replace `TaskListResponse`)
- `api/src/app/core/calls/schemas.py`
- `api/src/app/core/campaigns/schemas.py`
- `api/src/app/core/catalog/schemas.py`
- `api/src/app/core/appointments/schemas.py`
- `api/src/app/core/walk_ins/schemas.py`
- Matching `router.py` files updating `response_model`
- `api/tests/shared/test_pagination_schema.py` (create)

## Plan
1. Create the generic in `shared/schemas/pagination.py` using `pydantic.BaseModel` + `typing.Generic[T]`.
2. Grep for `class \w+ListResponse` under `app/core/` → 16+ hits.
3. Replace each with `ListResponse = PaginatedResponse[ItemSchema]` (alias preserves the name routers import).
4. Update OpenAPI schema generation — confirm Swagger still renders distinct schemas (`PaginatedResponse_Contact_`, etc.).
5. Run `uv run pytest` to confirm serialization tests still pass.

## DB changes / migrations
None.

## Tests to add
- Unit test in `tests/shared/test_pagination_schema.py`: instantiate `PaginatedResponse[dict]` with sample data, assert fields and JSON shape.
- Smoke test: hit `GET /api/v1/contacts?page=1&size=10` and assert response matches the generic shape.

## Verification checklist
- `uv run pytest -q` — green.
- Open Swagger at `/docs` — every list endpoint shows `items/total/page/size` schema.
- Browser smoke: open Contacts list page in Ajay's Workspace — table loads, pagination footer works.

## Self-check (10 rules)
- [ ] No `/core` → `/packs` imports.
- [ ] Every list endpoint still filters by `org_id` (untouched by this refactor).
- [ ] Backwards-compatible alias names preserved where routers re-export.
- [ ] No commented-out classes left behind — old `ListResponse` definitions deleted.

## Stop & report
Files changed · LOC removed · Tests added · "Awaiting your 'proceed'".
