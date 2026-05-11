# Step 6.3 — Performance pass

**Goal:** Add indexes on hot paths, JSONB GIN indexes on `custom_data` for entities filtered by custom fields, pagination/cursor patterns, N+1 audit.
**Phase:** 6
**Depends on:** prior phases
**Status:** Pending

## Scope
**In-scope:**
- Audit slow queries (`pg_stat_statements`, log slow queries > 100ms).
- Add missing indexes:
  - GIN on `custom_data` for: contacts, leads, walk_ins, appointments, custom_orders.
  - Composite indexes on common filters (`org_id, created_at desc` already there from earlier; add for any missing).
- Convert offset-based pagination to cursor-based on long lists (contacts, leads, conversations, messages, audit_logs).
- N+1 audit: replace lazy-loads with `selectinload`/`joinedload` where lists fan out.
- Add `EXPLAIN ANALYZE` capture script for the top 20 queries.

## Files to touch
- `api/alembic/versions/0034_perf_indexes.py` (created)
- multiple `*/router.py` files (modified — cursor params)
- multiple `*/service.py` files (modified — eager loading)

## Plan
1. Run app under realistic seed data; capture pg_stat_statements top-20.
2. Add GIN + composite indexes per finding.
3. Refactor pagination to cursor; keep offset for small lists.
4. Add `selectinload` to known fan-out queries.
5. Re-measure; document in `docs/performance.md`.

## Tests to add
- `tests/test_pagination_cursor.py` — cursor stable across inserts.

## Verification checklist
**Backend:**
- top-20 slow queries reduced.
- list endpoints respond < 200ms p50 on 10k-row dataset.

## Self-check (10 rules)
- [ ] No regressions in RLS or org isolation.
- [ ] No TODOs.

## Stop & report
Await "proceed" before Step 6.4.
