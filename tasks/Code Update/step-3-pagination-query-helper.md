# Step 3 — `apply_offset_pagination` helper

**Goal:** Replace the `.offset((page - 1) * size).limit(size)` + count pattern duplicated across 11+ services with one shared helper.
**Track:** Code Update — Foundations
**Depends on:** Step 1 (uses `PaginatedResponse[T]`)
**Status:** Not started

## Scope
**In-scope:**
- Create `api/src/app/shared/db/pagination.py::paginate(session, stmt, *, page, size)` returning `(rows, total)`.
- Helper runs both the count query (`select(func.count()).select_from(stmt.subquery())`) and the data query in one place.
- Migrate the 11+ services using this pattern.

**Out of scope:**
- Cursor pagination.
- Pre-counted endpoints (e.g. infinite scroll) — they keep their own logic.

## Files to touch
- `api/src/app/shared/db/pagination.py` (create)
- `api/src/app/core/contacts/service.py` (`:385-388`)
- `api/src/app/core/leads/service.py`
- `api/src/app/core/tasks/service.py`
- `api/src/app/core/appointments/service.py`
- `api/src/app/core/campaigns/service.py`
- `api/src/app/core/calls/service.py`
- `api/src/app/core/catalog/service.py`
- `api/src/app/core/walk_ins/service.py`
- `api/src/app/core/conversations/service.py`
- `api/src/app/core/reviews/service.py`
- `api/src/app/core/billing/service.py`
- `api/tests/shared/test_pagination.py` (create)

## Plan
1. Implement helper: clamp `page >= 1`, `1 <= size <= 200`, run count, run data with `offset/limit`, return tuple.
2. Grep `\.offset\(.*page.*\)\.limit\(` → 11+ hits.
3. Replace each list service method. Combine with `PaginatedResponse[T]` from Step 1: `PaginatedResponse(items=rows, total=total, page=page, size=size)`.
4. Confirm router signatures unchanged.

## DB changes / migrations
None.

## Tests to add
- Helper returns correct slice when total > size.
- Helper clamps `page < 1` to 1, `size > 200` to 200.
- Helper returns `(items=[], total=0, page=1, size=N)` for empty queries.

## Verification checklist
- `uv run pytest tests/shared/test_pagination.py` — green.
- Browser smoke: paginate through Contacts list — page 1, 2, last page all render with correct counts.

## Self-check (10 rules)
- [ ] Helper preserves whatever `.where(org_id == ...)` filters the caller already applied.
- [ ] No size > 200 (rate-limiting guard).
- [ ] Old offset/limit blocks deleted, not commented.

## Stop & report
Files changed · LOC removed · Tests added · "Awaiting your 'proceed'".
