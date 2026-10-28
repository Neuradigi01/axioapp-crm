# Step 5.6 — Global search

**Goal:** Global search across contacts, leads, products, orders, invoices, custom orders. Postgres full-text search initially. Header search bar wired up.
**Phase:** 5 — Core CRM v1 Launch
**Depends on:** most prior modules
**Status:** Pending

## Scope
**In-scope:**
- Backend: `app/core/search/`:
  - Migrations to add `tsvector` generated columns (or trigger-maintained) on each searched table.
  - GIN indexes on the tsvector columns.
  - Service `search(q, types?, limit=20)` returning unified results with type + id + label + snippet.
  - Endpoint `GET /search?q=...&types=contacts,leads,...`.
- Frontend:
  - Header search bar (already present) wired to `/search` with debounced input.
  - Dropdown rendering grouped results; click → routes to detail page.

## Files to touch
- `api/src/app/core/search/{__init__,service,router,module}.py` (created)
- `api/alembic/versions/0033_search_tsvectors.py` (created)
- `app/src/app/features/user/core/layout/header.component.ts/.html` (modified — wire search)
- `app/src/app/features/user/core/search/search-results-popover.component.ts/.html` (created)

## Plan
1. Add `search_vector tsvector` columns where useful with `STORED` generated expressions for the most-queried fields.
2. GIN indexes.
3. Service queries each type via UNION ALL, ranks by `ts_rank`, returns top N.
4. Frontend popover with grouped list.

## Tests to add
- `tests/test_search.py` — multi-type ranking + RLS isolation.

## Verification checklist
**Backend/Frontend:**
- type "Sharma" in header → results across contacts/leads.
- click → routes to detail.

## Self-check (10 rules)
- [ ] org_id filter on every union branch (RLS still applies; double-check).

## Stop & report
Await "proceed" before Step 6.3.
