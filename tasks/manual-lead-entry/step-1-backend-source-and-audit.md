# Step 1 — Backend: `lead.source` enum column + audit event on create

**Goal:** Add a NOT NULL `source` enum column to the `leads` table covering all five future ingestion channels (`manual | bulk_import | widget | google_ads | meta_ads`), default it to `manual` so existing callers keep working, and emit a `lead.created` audit event on every write so later channels can reuse the same event shape.
**Track:** Manual Lead Entry
**Status:** Done — `lead_source` PG enum + `leads.source` NOT NULL column shipped via migration `0040_lead_source`. `LeadSource` `enum.Enum` declared in `core/leads/models.py`; `LeadCreate` defaults to `manual`, `LeadOut` exposes `source`. `create_lead` passes the value through and the existing `audit.log("leads.created", ...)` event now carries `source` in its `after` snapshot — verified end-to-end against the dev DB (created lead with `source='widget'` → audit row `after.source == 'widget'`; omitting source → defaults to `'manual'`). Migration round-trips up→down→up cleanly. No `core/audit/events.py` created — codebase uses plain string action names; no constants registry exists, so introducing one would be an unused abstraction (Rule 10).
**Depends on:** Phase 1.7 (audit logs), Phase 2.11 (Leads backend).

---

## Scope

In-scope:

- Alembic migration adding `source` (PG enum `lead_source_enum`) to `leads`, NOT NULL, default `manual`. Backfill existing rows to `manual` in the same migration.
- SQLAlchemy `Lead.source` mapped column + Python `LeadSource` `StrEnum`.
- `LeadCreate` Pydantic schema gains optional `source: LeadSource = LeadSource.MANUAL`. `LeadRead` / `LeadList` expose `source` in responses.
- `LeadService.create()` emits an `lead.created` audit event with payload `{lead_id, source, actor_user_id, org_id}`.
- Audit event key `lead.created` declared in the central audit registry (mirror existing event declarations in `core/audit/events.py`).
- Tests pinning enum membership, default behaviour, audit emission shape, and round-trip on the API.

Out of scope:

- No frontend changes. Step 2 handles the badge + floating button.
- No dedup logic — that lands in bulk-import and ad-integrations tracks.
- No `LeadIngestionService` abstraction — each channel keeps its own `service.create()` path; they all just stamp `source` consistently.
- No new permission keys. `leads.create` already gates the endpoint.

## DB changes / migrations

```python
# alembic: 0XXX_add_lead_source.py

from alembic import op
import sqlalchemy as sa

lead_source = sa.Enum(
    "manual", "bulk_import", "widget", "google_ads", "meta_ads",
    name="lead_source_enum",
)

def upgrade():
    lead_source.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "leads",
        sa.Column("source", lead_source, nullable=False, server_default="manual"),
    )
    # Existing rows backfilled by server_default; drop the default afterwards
    # so future inserts must explicitly state intent (Pydantic default covers it).
    op.alter_column("leads", "source", server_default=None)

def downgrade():
    op.drop_column("leads", "source")
    lead_source.drop(op.get_bind(), checkfirst=True)
```

Verify both `alembic upgrade head` and `alembic downgrade -1` run clean. RLS on `leads` is unaffected (existing policy continues to filter by `org_id`).

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_lead_source.py` | created |
| `api/src/app/core/leads/models.py` | modified — add `source: Mapped[LeadSource]` |
| `api/src/app/core/leads/schemas.py` | modified — `LeadSource` enum + add `source` to `LeadCreate`/`LeadRead`/`LeadList` |
| `api/src/app/core/leads/service.py` | modified — `create()` writes `source` + emits audit event |
| `api/src/app/core/audit/events.py` | modified (small) — declare `LEAD_CREATED = "lead.created"` constant |
| `api/tests/test_leads_source.py` | created — enum membership, default, audit-event shape, API round-trip |

**6 files. 1 migration.** Inside rule-8 budget.

## Plan

1. Declare the Python `LeadSource(StrEnum)` in `leads/schemas.py` with the five values. Reuse the same string values in the PG enum.
2. Write the migration. Run upgrade against a fresh DB; verify the column exists and existing rows (if any from seed) backfilled to `manual`. Run downgrade; verify clean.
3. Add `Mapped[LeadSource]` to `Lead` in `models.py`.
4. Widen `LeadCreate` with `source: LeadSource = LeadSource.MANUAL`. Widen `LeadRead` and `LeadList` to expose `source`.
5. In `LeadService.create()`, after the successful flush, call `audit.emit(LEAD_CREATED, {lead_id, source, actor_user_id, org_id})`. The actor id is whatever the existing service signature already carries (likely `current_user.id`); when the caller is `None` (system-created later from webhooks/widget) pass `None`.
6. Declare the `LEAD_CREATED` constant in `core/audit/events.py` so other tracks can reuse it without redeclaring.
7. Tests.

## Tests

`api/tests/test_leads_source.py`:

- **Enum membership:** `set(LeadSource) == {"manual", "bulk_import", "widget", "google_ads", "meta_ads"}`. Catches accidental rename.
- **Default applied:** `POST /api/v1/leads` without `source` in body → response has `source == "manual"`; row in DB has `source == "manual"`.
- **Explicit source accepted:** `POST /api/v1/leads` with `source: "bulk_import"` → response and DB both reflect `bulk_import`. (Sanity for the next track.)
- **Invalid source rejected:** `POST /api/v1/leads` with `source: "facebook"` → 422.
- **Audit event emitted:** after a successful create, the audit log has one new `lead.created` row with the matching `lead_id`, `source`, `actor_user_id`, `org_id`. Use the existing audit-log test helper (mirror pattern from `tests/test_audit_*.py`).
- **NOT NULL after migration:** insert a raw row at the SQL level without `source` → fails with NOT NULL violation.

## Smoke

```powershell
# Migration runs cleanly
docker exec template_api-api-1 uv run alembic upgrade head
docker exec template_api-api-1 uv run alembic downgrade -1
docker exec template_api-api-1 uv run alembic upgrade head

# Tests pass
docker exec template_api-api-1 uv run pytest tests/test_leads_source.py -v

# Manual round-trip with curl (or use the API docs)
$token = "<owner JWT>"
curl -X POST http://localhost:8000/api/v1/leads `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"contact_id": "<existing contact uuid>", "title": "Manual smoke test"}'
# Expect 201 with source: "manual" in the response body.
```

## Risks

- **Existing rows on production:** the `server_default='manual'` backfill is correct semantically (any pre-existing lead was created by a user typing in the modal). Document this in the migration's docstring so future readers don't wonder.
- **Audit event shape lock-in:** because every later channel will reuse `lead.created`, the payload shape we land here is permanent. Keep it minimal — `{lead_id, source, actor_user_id, org_id}`. Anything channel-specific (UTM tags, webhook id, import job id) goes into a separate sibling event (e.g. `lead.ingested_from_widget`) emitted by the respective channel's track.
- **Frontend caller drift:** `LeadCreate` widening is additive — existing frontend callers omitting `source` still work because of the Pydantic default. No frontend change required in this step; Step 2 surfaces `source` on the read path only.

## Rollback

`alembic downgrade -1` removes the column and the enum type. Revert the four `.py` files. Audit-event constant in `core/audit/events.py` is unused if removed; safe to delete with the rest.
