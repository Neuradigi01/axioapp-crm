# Step 11 — Backend: Google worker parity for pipeline_stage

**Goal:** Extend Step 10's per-form pipeline_stage override to the Google Ads worker so both providers behave identically. Step 10 wired it into Meta's `tasks.py`; this step is the mechanical mirror for `google/tasks.py`.
**Track:** Ad Integrations
**Status:** COMPLETED
**Depends on:** Step 10 (`tbl_integration_subscriptions.pipeline_stage` exists + service validates it).

---

## Scope

In-scope:

- **`core/integrations/google/tasks.py`** — inside the `ingest_lead(...)` call, pass `pipeline_stage=subscription.pipeline_stage` on the `LeadCreate` argument, identical to the Meta shape.

Out of scope:

- Frontend UI (Step 12).
- Owner-assignment override (future).

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/integrations/google/tasks.py` | modified — pass subscription's pipeline_stage into LeadCreate |

One file, one-line semantic change.

## Verification

- A Google Ads webhook delivery for a subscription with `pipeline_stage="qualified"` produces a lead in stage `qualified`.
- The same subscription with `pipeline_stage=NULL` produces a lead in the org's default first stage (unchanged pre-Step-11 behaviour).
- Bad stage keys still 422 at the write-time endpoint (Step 10 covers that).

## Self-check

- ✅ 10 rules: no `/core → /packs` import; existing patterns preserved; no TODOs.
- ✅ Router → Service → DAL: worker is `tasks.py` (an existing documented helper module); no SQL added; no transaction discipline drift.
- ✅ Reuse: leverages Step 10's schema, validation, and `LeadCreate.pipeline_stage`. Zero new endpoints.
- ✅ Query efficiency: no change — one Graph API call per lead as before.
