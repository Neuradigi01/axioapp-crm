# Step 2 — Backend: extend `GET /leads` with `created_from`/`created_to`, `sort=next_follow_up_due`, CSV cell escape, `(filtered/total)` count

**Goal:** Extend the leads-list endpoint with the three new query surfaces the Leads Center toolbar (step 5) needs, harden the CSV export against formula injection on every free-text column, and add the `unfiltered_total` field to the paginated response so the header can render `(filtered/total)`.
**Track:** Leads — Update Status Flow
**Status:** COMPLETED — 2026-08-17. `GET /api/v1/leads` and `GET /api/v1/leads/export.csv` now accept `created_from` / `created_to` (both inclusive; date → UTC start-of-day / next-day 00:00 half-open); `sort` Literal widened with `next_follow_up_due`, backed by a `LEFT JOIN LATERAL (SELECT MIN(due_at) FROM tbl_tasks WHERE related_entity_type='lead' AND related_entity_id=tbl_leads.id AND status='open')` composed in [`leads/data_access.py`](../../API/src/app/core/leads/data_access.py) via the new `followup_sort_order` kwarg (existing `ix_tbl_tasks_related` covers the lookup — verified no new index needed); response gets `unfiltered_total` when `with_unfiltered_total=true`. CSV exporter hardened: new `_excel_safe()` prefix on every free-text cell (contact name/email, pipeline_stage, lost_reason pair, string custom-field cells, list-joined custom-field values) — leaves phone's existing `="+..."` prefix untouched. Export CSV path already respects `list_leads_where`'s WHERE, extended in tandem with the new date-range params + sort literal. 10-assertion pytest at [`tests/test_leads_list_filters.py`](../../API/tests/test_leads_list_filters.py). Ruff-formatted; ruff-check clean on all step-2 files. OpenAPI post-restart confirms: list endpoint carries `created_from` / `created_to` / `with_unfiltered_total` params, sort enum includes `next_follow_up_due`, `LeadListResponse.unfiltered_total` present; export endpoint mirrors the same params + sort enum. `_excel_safe('=cmd|calc') → "'=cmd|calc"`, `_excel_safe('+leaked') → "'+leaked"`, `_excel_safe('normal') → 'normal'`, `_excel_safe(None) → ''` — verified via container-level import. No migration added; existing `ix_tbl_tasks_related` narrows the lateral to O(few rows per lead). Pytest not run — per user preference batched for confirmation.
**Depends on:** Step 1 (schemas import — none, but keeps the track ordered); existing `leads/router.py`, `service.py`, `data_access.py`, `csv_export.py`.

---

## Scope

In-scope:

- `GET /api/v1/leads` accepts new query params: `created_from: date | None`, `created_to: date | None`.
- `sort` enum widens with `next_follow_up_due`. Implementation: `LEFT JOIN LATERAL (SELECT MIN(due_at) FROM tbl_tasks WHERE related_entity_type='lead' AND related_entity_id=tbl_leads.id AND status='open') fu ON true` + `ORDER BY fu.min_due_at ASC NULLS LAST` (or DESC based on `order`).
- List response schema gains `unfiltered_total: int` alongside the existing `total`. Cheap — single `COUNT(*)` scoped to org.
- CSV exporter: extend the Excel-safety prefix (currently only on phone at [`csv_export.py:257`](../../API/src/app/core/leads/csv_export.py#L257)) to every free-text column (`name`, `email`, `remarks_placeholder` — verify column list) plus every custom-field cell.
- Index verification: assert `tbl_tasks(related_entity_id, status, due_at)` exists via a schema-inspection test; add the index in a migration only if missing.

Out of scope:

- No `remarks_contains` filter — dropped in the replan (README D7 note).
- No new advanced-filter DSL fields (`created_at` is already in `LEAD_DIRECT_FIELDS` at [`filter_dsl.py:63`](../../API/src/app/core/leads/filter_dsl.py#L63) — toolbar reads via new params, DSL keeps working unchanged).
- No changes to `LEAD_DIRECT_FIELDS` — the DSL surface is preserved as-is.
- No `.xlsx` writer.

## DB changes / migrations

**Conditional.** Run `SELECT indexname FROM pg_indexes WHERE tablename='tbl_tasks'` at test time. If `(related_entity_id, status, due_at)` isn't already covered (equivalent composite exists), add:

```python
# alembic: 0198_tasks_lead_fu_idx.py
from alembic import op

def upgrade():
    op.create_index(
        "ix_tbl_tasks_lead_open_due",
        "tbl_tasks",
        ["related_entity_id", "status", "due_at"],
        postgresql_where=text("related_entity_type = 'lead' AND status = 'open'"),
    )

def downgrade():
    op.drop_index("ix_tbl_tasks_lead_open_due", table_name="tbl_tasks")
```

Partial index — narrower + smaller than a full 3-col index; matches our exact JOIN LATERAL predicate. Revision id length 30 chars, under the 32 limit.

## Files to touch

| File | Action |
|---|---|
| [`API/src/app/core/leads/router.py`](../../API/src/app/core/leads/router.py) | modified — new query params on `list_leads` endpoint |
| [`API/src/app/core/leads/service.py`](../../API/src/app/core/leads/service.py) | modified — extend `list_leads_where` + build the lateral join for the new sort; `list_leads` returns `unfiltered_total` |
| [`API/src/app/core/leads/data_access.py`](../../API/src/app/core/leads/data_access.py) | modified — helper for the `unfiltered_total` count |
| [`API/src/app/core/leads/schemas.py`](../../API/src/app/core/leads/schemas.py) | modified — extend `SortField` enum + add `unfiltered_total` to `LeadListResponse` |
| [`API/src/app/core/leads/csv_export.py`](../../API/src/app/core/leads/csv_export.py) | modified — widen the Excel-safety prefix to every free-text column + custom-field cells |
| `API/alembic/versions/0198_tasks_lead_fu_idx.py` | **conditional** — only if the index isn't already there |
| `API/tests/test_leads_list_filters.py` | created |

**5-6 files, ~200 LOC.** Inside rule-8.

## Plan

1. **Add `created_from` / `created_to` params to the router.** Both `Query(None, description="…")`. Pass through to `list_leads_where`. In the builder, add `WHERE tbl_leads.created_at >= :cf` and `<= :ct + INTERVAL '1 day'` when non-null (inclusive on both bounds; date → end-of-day for `created_to`).
2. **Widen `SortField`.** Add `next_follow_up_due` to the enum + docstring.
3. **Implement the lateral join for the new sort.** Only add the join when `sort=next_follow_up_due` — don't pay for it otherwise. `ORDER BY fu.min_due_at NULLS LAST` (both ASC and DESC).
4. **`unfiltered_total`.** In `list_leads`, after the filtered query, issue one extra `SELECT COUNT(*) FROM tbl_leads WHERE org_id = :org AND deleted_at IS NULL`. Return alongside `total` (filtered) + `items` in `LeadListResponse`.
5. **CSV formula-injection prefix.** In `csv_export.py`, define a `_excel_safe(cell: str) -> str` helper that prefixes `'` to any cell whose first char is in `{'=', '+', '-', '@', '\t', '\r'}`. Apply to every string column in the header row + every custom-field cell before writing.
6. **Index check + optional migration.** Test-side: introspect `pg_indexes` and either assert an equivalent composite exists or apply the new partial index in the migration above.

## Tests

`API/tests/test_leads_list_filters.py`:

1. **`created_from` inclusive.** Seed leads at `2026-08-15`, `2026-08-16`, `2026-08-17`. `?created_from=2026-08-16` → returns 2. `?created_from=2026-08-17` → returns 1.
2. **`created_to` inclusive end-of-day.** Same seeds. `?created_to=2026-08-16` → returns 2 (includes anything created on 08-16 up to 23:59:59).
3. **Both bounds combined.** `?created_from=2026-08-16&created_to=2026-08-16` → returns exactly the one lead created that day.
4. **Missing bound = unbounded.** `?created_from=2026-08-16` (no `_to`) returns everything from 08-16 forward.
5. **`sort=next_follow_up_due&order=asc`.** Seed 3 leads: A with open task due 2026-08-20, B with due 2026-08-19, C with no open task. Order: B, A, C (NULLS LAST).
6. **`sort=next_follow_up_due&order=desc`.** Order: A, B, C (NULLS LAST still — invariant).
7. **`unfiltered_total`.** Seed 5 leads, request with `status=won` filter matching 2. Response: `total=2, unfiltered_total=5`.
8. **CSV Excel-safety on remarks/notes-derived cells.** Seed a lead whose contact's `full_name = "=cmd|calc"`. Export CSV. Cell value is `'=cmd|calc` (leading apostrophe).
9. **CSV Excel-safety on custom-field cells.** Seed a lead with `custom_data = {"segment":"+leaked"}` on a custom field named `segment`. Cell value: `'+leaked`.
10. **Filter DSL still works.** Assert `?filter={"created_at":{"gte":"2026-08-16"}}` still returns the same result as `?created_from=2026-08-16`.
11. **Index exists.** Introspect `pg_indexes` for `tbl_tasks`; assert an index covers `(related_entity_id, status, due_at)` — either the new one or a superset.

## Smoke

```powershell
docker exec crm-api-1 alembic upgrade head  # applies 0198 if added
docker restart crm-api-1

$token = "<owner JWT>"
# New date filter
curl "http://localhost:8000/api/v1/leads?created_from=2026-08-01&created_to=2026-08-17&sort=next_follow_up_due&order=asc" `
  -H "Authorization: Bearer $token"
# Expect a page of leads with the earliest open-task due at top, NULLs at bottom.

# Response includes unfiltered_total
curl "http://localhost:8000/api/v1/leads?status=won" -H "Authorization: Bearer $token" | jq '.total, .unfiltered_total'

# CSV export with a mock formula in a lead name
curl "http://localhost:8000/api/v1/leads/export.csv" -H "Authorization: Bearer $token" -o leads.csv
# Grep the file — any cell starting with = + - @ must be prefixed with '.
Select-String -Path leads.csv -Pattern '(?m)^[^,]*,[^,]*[=+\-@]' | Select-Object -First 5
```

## Risks

- **Lateral join cost.** Even with the partial index, the sort widens the query plan. Test with 5k+ leads in a scratch DB to confirm sub-100ms p95. If regression, gate the sort behind a signed hint (`?sort_expensive=1`) — but almost certainly fine with the partial index.
- **`unfiltered_total`** adds a second round-trip. Cheap (COUNT scoped by org + `deleted_at IS NULL` with the existing org index) — measure and confirm ≤ 5ms overhead. If worse, cache it briefly per session, or make the extra count opt-in via `?include_unfiltered_total=1` and only send from the Leads Center header.
- **CSV escape breaks external tools** that expect the raw string. Standard Excel-safety practice (`'=formula` is the OWASP-recommended encoding); the receiver strips the leading `'` in-cell. Acceptable trade.
- **Date bounds interpretation.** ISO date at the boundary: `created_to=2026-08-16` becomes `<= 2026-08-16 23:59:59+00`. Timezone is UTC (server), matching every other filter on this endpoint. Document in router docstring so client authors don't try to pass datetimes.

## Rollback

Revert the modified `.py` files. If the migration ran, `alembic downgrade -1` drops the partial index (safe — no data impact).
