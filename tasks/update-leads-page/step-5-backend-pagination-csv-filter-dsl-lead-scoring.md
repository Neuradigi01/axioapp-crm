# Step 5 — Backend: cursor pagination + filter DSL + CSV export + `lead_score` column with rule engine

**Goal:** make the leads list endpoint scale past 500 leads (server-side cursor pagination), introduce a small JSON filter DSL that both the list endpoint and the scoring engine consume, ship a streaming CSV export endpoint that respects every active filter, and add a `lead_score` column whose value is computed from operator-defined rules. The CRUD endpoints for those rules ship in this step too; the admin UI for them is built in Step 7.

**Depends on:** Steps 1–4 backend (status workflow + `last_activity_at` + reassign + convert all in place). No new dependencies on contacts.

## Files changed

### New
- `API/alembic/versions/0070_leads_pagination_score_and_scoring_rules.py`
- `API/src/app/core/leads/filter_dsl.py` — DSL parser + SQL builder.
- `API/src/app/core/leads/csv_export.py` — streaming CSV writer.
- `API/src/app/core/leads/scoring.py` — engine + recompute hooks.

### Modified
- `API/src/app/core/leads/models.py` — + `lead_score`, + `LeadScoringRule` model.
- `API/src/app/core/leads/schemas.py` — + `LeadListResponse` paged shape, + scoring rule schemas, + `lead_score` on `LeadOut`/`LeadListItem`.
- `API/src/app/core/leads/service.py` — refactor `list_leads` for cursor pagination + filter DSL ingestion; add `create_/update_/delete_scoring_rule`; hook score recompute into `create_lead` / `update_lead`.
- `API/src/app/core/leads/router.py` — replace `GET /leads` shape with paged response; add `GET /leads/export.csv`; add `/leads/scoring-rules` CRUD.
- `API/src/app/core/leads/module.py` — register `leads.export` and `leads.scoring.manage` permission keys.

### Tests
- `API/tests/core/leads/test_pagination_and_csv.py` (new)
- `API/tests/core/leads/test_lead_scoring.py` (new)

## Migration `0070_leads_pagination_score_and_scoring_rules.py`

- `ALTER TABLE leads ADD COLUMN lead_score INTEGER NOT NULL DEFAULT 0`
- `CREATE INDEX ix_leads_org_score_desc ON leads (org_id, lead_score DESC)`
- `CREATE INDEX ix_leads_org_created_id ON leads (org_id, created_at DESC, id DESC)` — keyset cursor on default sort.
- `CREATE INDEX ix_leads_org_last_activity_id ON leads (org_id, last_activity_at DESC NULLS LAST, id DESC)` — keyset on last-activity sort.
- `CREATE TABLE lead_scoring_rules (`
  - `id UUID PRIMARY KEY DEFAULT gen_random_uuid(),`
  - `org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,`
  - `name VARCHAR(120) NOT NULL,`
  - `condition JSONB NOT NULL,` *(filter DSL fragment; see below.)*
  - `points INTEGER NOT NULL CHECK (points BETWEEN -100 AND 100),`
  - `active BOOLEAN NOT NULL DEFAULT TRUE,`
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),`
  - `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`
- `CREATE INDEX ix_lead_scoring_rules_org_active ON lead_scoring_rules (org_id, active)`
- **RLS** on `lead_scoring_rules`: `ENABLE ROW LEVEL SECURITY`; `CREATE POLICY ... USING (org_id = current_setting('app.current_org_id')::uuid)` — matches every other tenant table per Rule 2.
- `downgrade()` drops the policy, indexes, table, column.
- **No backfill needed** — `lead_score` defaults to 0; recomputation happens on next write or via the Celery job introduced below.

## `filter_dsl.py`

A small, server-only JSON DSL shared by the list endpoint, CSV export, and scoring rule conditions.

```python
"""Lead filter DSL — JSON-in, SQLAlchemy-clauses-out.

Shape:
    {
      "all": [<clause>, ...],   # AND group (optional)
      "any": [<clause>, ...]    # OR group (optional)
    }

Clause:
    {"field": "<field>", "op": "<op>", "value": <any>}

Fields (whitelist, enforced — no arbitrary SQL):
    status, source, assigned_to_id, lead_score, budget, last_activity_at,
    created_at, contact_name, contact_phone, contact_email, linked_deal_id,
    custom_data.<key>   # dotted access into JSONB

Ops:
    eq, neq, in, nin, gt, gte, lt, lte, contains, starts_with,
    between, is_empty, is_not_empty
"""
```

API surface:
- `parse(dsl: dict) -> Filter` — validates structure; raises `ValueError` (mapped to `422`) on unknown field/op or malformed shape.
- `to_sqlalchemy(filter_: Filter, model: type[Lead]) -> ColumnElement` — returns a single boolean clause for use in `.where(...)`.
- `matches(filter_: Filter, lead: Lead) -> bool` — in-memory evaluation, used by the scoring engine to score a single lead without round-tripping the DB.

**Hard limits** (cheap DoS guardrails):
- Max 20 clauses across `all` + `any` combined.
- Max depth 1 (no nested groups in v1 — keeps the SQL builder simple; nested support deferred).
- Custom-field key max length 64; rejected if not present in `custom_field_definitions` for the org.

## `csv_export.py`

- `stream_leads_csv(session, org_id, filter_, sort, order) -> AsyncIterator[bytes]`
  - Header row built from a fixed list of standard columns + every active custom field definition for the org.
  - Body: server-side cursor over the filtered query, yielding ~1000 rows per chunk.
  - Date columns formatted as ISO-8601 UTC; JSONB `custom_data` flattened to per-column cells.
  - Phone numbers emitted as E.164 with a leading `="` quote-prefix to defeat Excel's auto-stripping of leading zeros.
- Router endpoint uses FastAPI `StreamingResponse(media_type="text/csv")` with `Content-Disposition: attachment; filename="leads-<org>-<utc-date>.csv"`.

## `scoring.py`

```python
"""Lead scoring engine.

A rule is an active row in `lead_scoring_rules`. Score = clamp(sum of
points of matching rules, 0, 100). Recompute is per-lead and triggered:

  - on create_lead   (after commit)
  - on update_lead   (after commit, when any rule-relevant field changed)
  - via the Celery beat job `recompute_all_lead_scores` (hourly; per-org)

The hourly job exists because scoring rules themselves can be edited; an
edit invalidates every lead's score for that org.
"""
```

API surface:
- `compute_score(lead: Lead, rules: list[LeadScoringRule]) -> int`
- `recompute_lead(session, lead: Lead) -> None` — fetches active rules for the org, computes, updates `lead.lead_score`, flushes (no commit — caller decides).
- `recompute_org_scores(session, org_id: UUID) -> int` — bulk update, returns count.
- Celery task `recompute_all_lead_scores` registered against Celery beat, every 1h. Iterates orgs; calls `recompute_org_scores` per org.

**Rule-relevant fields** (for the change-detection hook in `update_lead`): the union of fields referenced by any active rule's `condition`. Cached per-org for 60s. If unknown, falls back to "always recompute."

## `service.py` — list refactor

`list_leads(...)` signature:

```python
async def list_leads(
    session: AsyncSession,
    *,
    org_id: UUID,
    cursor: str | None = None,
    limit: int = 50,
    sort: Literal["created_at", "last_activity_at", "lead_score", "contact_name"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    filter_dsl: dict | None = None,
    # existing convenience filters (kept for backward compat; translated to DSL clauses internally):
    q: str | None = None,
    status: str | None = None,
    source: str | None = None,
    assigned_to_id: UUID | None = None,
    last_activity_lt: datetime | None = None,
    last_activity_gt: datetime | None = None,
    scope: Literal["mine", "team", "all"] = "all",
    with_total: bool = False,
) -> LeadListResponse:
    ...
```

- `limit` clamped to `[1, 200]`. Default 50.
- Cursor is base64(`{"v": <last_sort_value_iso>, "id": "<last_id>"}`); decoded server-side. Tampering → `400`.
- Keyset where-clause: `(sort_col, id) < (cursor.v, cursor.id)` for `desc`; reversed for `asc`. Uses the indexes created in 0070.
- `with_total=true` runs a separate `SELECT count(*)` against the same filter — opt-in because it negates the keyset performance benefit on large tables. Surfaced for the FE to show "X leads" when the user explicitly asks.
- Response:

```python
class LeadListResponse(BaseModel):
    items: list[LeadListItem]
    next_cursor: str | None
    total: int | None  # only when with_total=true
```

**Backward compatibility:** the legacy unpaginated callers (none in tree after Step 4) would break. Verified via grep — only the leads page and one report consume this; both are updated within this track / future steps. `with_total=true` is what the existing FE will pass on first page so the count keeps working.

## `service.py` — scoring rule CRUD

Standard create / update / delete / list inside the leads service module (no separate file — keeps surface tight). Permission `leads.scoring.manage` enforced at the router.

On any mutation: invalidate the rule-relevant-fields cache for the org and enqueue `recompute_org_scores` (deferred via Celery, not inline, because it can be heavy).

## `router.py`

| Method | Path | Permission |
|---|---|---|
| `GET` | `/leads` | `leads.read` — returns `LeadListResponse` |
| `GET` | `/leads/export.csv` | `leads.export` (new) |
| `GET` | `/leads/scoring-rules` | `leads.scoring.manage` (new) |
| `POST` | `/leads/scoring-rules` | `leads.scoring.manage` |
| `PATCH` | `/leads/scoring-rules/{id}` | `leads.scoring.manage` |
| `DELETE` | `/leads/scoring-rules/{id}` | `leads.scoring.manage` |

`GET /leads` accepts `filter` as a JSON-encoded query param (URL-encoded). Convenience filters (`status`, `source`, etc.) are kept; they're translated into DSL clauses inside the service and `AND`ed with any caller-supplied `filter`.

## `module.py`

Register two new keys:
- `leads.export` — granted to Owner + Admin templates by default.
- `leads.scoring.manage` — granted to Owner only by default. Editable by Admin per `project_rbac_requirements.md`.

## `models.py`

- `Lead.lead_score: Mapped[int]` — `Integer, nullable=False, default=0`.
- New `LeadScoringRule` model with `__tablename__ = "lead_scoring_rules"`; relationship back to `Organization`. Standard `org_id` Mapped FK.

## Test `test_pagination_and_csv.py`

1. Seed 130 leads. `GET /leads?limit=50` returns 50 + non-null `next_cursor`. Following the cursor twice exhausts the set (50 + 50 + 30).
2. `with_total=true` returns accurate count, identical across pages.
3. Sort by `lead_score desc` orders correctly with keyset.
4. `filter` param with `{"all":[{"field":"status","op":"eq","value":"qualified"}]}` filters correctly.
5. Unknown field in filter → `422`.
6. `GET /leads/export.csv` streams a `text/csv` body whose row count matches an unpaginated count for the same filter.
7. Caller without `leads.export` → `403`.
8. Phone column is `="+919..."` (Excel-safe).

## Test `test_lead_scoring.py`

1. Create rule "Mumbai metro" `{field: city, op: eq, value: Mumbai}` worth 20 → lead with city=Mumbai scores 20 on next write.
2. Two matching rules sum; clamped to 100.
3. Inactive rule does not contribute.
4. Editing a rule enqueues an org-wide recompute (mocked Celery, assert call args).
5. Cross-tenant rule create → `403` / `422`.
6. `recompute_org_scores` updates all leads' `lead_score` and returns the count touched.
7. Caller without `leads.scoring.manage` → `403` on POST/PATCH/DELETE.

## Acceptance

- `uv run alembic upgrade head` succeeds; `\d lead_scoring_rules` shows columns + RLS.
- `uv run pytest tests/core/leads -k "pagination or csv or lead_scoring"` passes.
- Existing tests still pass (state-machine + reassign + convert + last-activity).
- Manual smoke: `curl /leads?limit=2&with_total=true` returns expected shape; `curl /leads/export.csv` streams.

## Self-check vs the 10 rules

- ✅ Rule 1 — no pack imports.
- ✅ Rule 2 — `lead_scoring_rules` has `org_id` + RLS from day one.
- ✅ Rule 3 — `lead_score` is a first-class column (sortable / indexable); not custom_data.
- ✅ Rule 6 — `leads.export` + `leads.scoring.manage` registered via module.
- ✅ Rule 7 — `pack.yaml` untouched; the engine reads org-scoped rules from the DB, not from any pack manifest.
- ⚠️ Rule 8 — 11 files. At the upper bound; if the filter_dsl SQL builder grows beyond ~150 LOC during implementation, split CSV export into Step 5b and stop-and-report mid-stream.
- ✅ Rule 9 — stop-and-report after this step.
- ✅ Rule 10 — no TODOs; scoring engine ships with Celery hourly recompute wired in.

## Stop-and-report template

> ✅ Step 5 complete.
> **Files changed:** 11 (1 migration, 3 new modules, 5 modified leads, 2 new tests).
> **What you can verify:**
> 1. `uv run alembic upgrade head` → `\d leads` shows `lead_score`; `\d lead_scoring_rules` shows the table + RLS.
> 2. `GET /leads` returns the paged response shape with `next_cursor`.
> 3. `GET /leads/export.csv` streams a CSV (try with `curl -OJ`).
> 4. POST a rule with `condition = {"all":[{"field":"status","op":"eq","value":"qualified"}]}`, points=30 → next write on any qualified lead lifts its score by 30.
> 5. Celery beat shows `recompute_all_lead_scores` scheduled hourly.
> **Tests added:** `test_pagination_and_csv.py` (8), `test_lead_scoring.py` (7).
> **Raw INSERT SQL** for seeding a default rule on Ajay's Workspace:
> ```sql
> INSERT INTO lead_scoring_rules (org_id, name, condition, points, active)
> VALUES ('41f9ede9-41b3-44ce-b489-3004566d4068', 'Qualified', '{"all":[{"field":"status","op":"eq","value":"qualified"}]}', 30, true);
> ```
> **Self-check:** all 10 rules ✅ (Rule 8 noted at upper bound).
> Awaiting **"proceed"** before Step 6 (frontend pagination + columns + CSV + advanced filter UI).
