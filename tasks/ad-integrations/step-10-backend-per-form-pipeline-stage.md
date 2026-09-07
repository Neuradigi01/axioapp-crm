# Step 10 — Backend: per-form pipeline_stage on subscriptions

**Goal:** Give each `tbl_integration_subscriptions` row an optional `pipeline_stage` (nullable text). When set, the ad-webhook worker uses it as the ingested lead's initial stage; when null, the shared `ingest_lead` service falls back to the org's default first stage — same behaviour as today. Owner override for "leads from Form X go to Sales Pipeline stage `demo_scheduled`" without any UI change to the mapping editor (that's Step 12).
**Track:** Ad Integrations
**Status:** COMPLETED (migration awaiting your `run.cmd upgrade`)
**Depends on:** Step 8 (`tbl_integration_subscriptions` + `PUT /subscriptions/{id}` exist), Step 9 (per-form Attach/Edit-Mapping UI exposes rows to modify).

---

## Scope

In-scope:

- **DB migration (`0219_subs_pipeline_stage`)** — add `pipeline_stage TEXT NULL` to `tbl_integration_subscriptions`. Nullable + no default so every existing row stays functional (worker branches on `is not None`).

- **Model** — one `Mapped[str | None]` column on `IntegrationSubscription`.

- **Schemas** — extend `IntegrationSubscriptionRead`, `IntegrationSubscriptionCreate`, `IntegrationSubscriptionUpdate` with `pipeline_stage: str | None = Field(default=None, min_length=1, max_length=64)` (matches `LeadCreate.pipeline_stage`).

- **Service — write-time validation.** On `create_subscription` / `update_subscription`, if `pipeline_stage` is provided, resolve the org's `leads` pipeline and confirm the stage key exists. Reuse the existing `_resolve_initial_stage`-style pattern from `leads.service` — a lightweight join, no round-trip beyond the write. Bad key → 422.

- **Meta worker (`core/integrations/meta/tasks.py`)** — after `_apply_mapping`, if `subscription.pipeline_stage` is set, pass it through on the `LeadCreate(...)` call. `ingest_lead` and the lead service already know what to do with it (default-fallback path unchanged when None).

- **Tests** — extend `API/tests/test_meta_oauth.py` (or the closest existing test surface for subscriptions) with:
  - Round-trip: create subscription with `pipeline_stage="qualified"` → row persisted, `IntegrationSubscriptionRead.pipeline_stage == "qualified"`.
  - Invalid stage → 422.
  - Update path — flip a subscription from null → `"demo_scheduled"` and back.

Out of scope:

- **Owner (assignee) override.** Deferred to Step 11. Router still `pick_assignee()`s.
- **Frontend UI** to set the field. Deferred to Step 12 (extends the mapping editor modal with a Pipeline Stage dropdown).
- **Google worker parity.** Deferred to Step 11 — Meta only for this step so the schema+plumbing lands isolated for review; Google is a mechanical copy once Meta's shape is settled.
- **Historical backfill.** Every existing row stays `pipeline_stage=NULL` — old behaviour preserved.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0219_subs_pipeline_stage.py` | created — add nullable text column |
| `api/src/app/core/integrations/models.py` | modified — one column on `IntegrationSubscription` |
| `api/src/app/core/integrations/schemas.py` | modified — extend Read/Create/Update with `pipeline_stage` |
| `api/src/app/core/integrations/service.py` | modified — validate + persist on create/update |
| `api/src/app/core/integrations/meta/tasks.py` | modified — pass `subscription.pipeline_stage` into `LeadCreate` when set |
| `api/tests/test_meta_oauth.py` (or nearest) | modified — round-trip + invalid-stage assertions |

Six files, zero new modules, ~200 LOC.

## Verification

- `run.cmd upgrade` completes without error; `alembic downgrade -1` cleanly removes the column.
- `POST /api/v1/integrations/subscriptions` with `pipeline_stage="qualified"` returns 201 with the field echoed.
- `POST /api/v1/integrations/subscriptions` with `pipeline_stage="not-a-real-stage"` returns 422.
- Simulated Meta lead payload through the worker: subscription with `pipeline_stage="qualified"` → resulting `Lead.pipeline_stage == "qualified"`. Same payload with the subscription reset to null → default first-stage assignment (whatever the org's leads pipeline seed produces).

## Self-check

- ✅ 10 rules: `/core` untouched from `/packs`; `org_id` + `tbl_` prefix preserved; custom_data model untouched; forms still render dynamically; registries unchanged; ≤10 files; no TODOs.
- ✅ Router → Service → DAL: router.py unchanged; service.py owns validation + transaction; DAL untouched (using existing update path).
- ✅ Reuse: leverages existing `LeadCreate.pipeline_stage`, existing `_resolve_initial_stage` validation pattern, existing subscription update endpoint.
- ✅ Query efficiency: pipeline validation is a single join; worker still one Graph API call per lead.
