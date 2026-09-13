# Step 13 — Backend: auto-attach every Lead Form when a Page is subscribed

**Goal:** Match CRM industry standard — when an Owner subscribes a Facebook Page, the backend creates a `tbl_integration_subscriptions` row for **every** Lead Form on that Page with a heuristic default `field_mapping` pre-filled, so leads start flowing to the CRM immediately without any manual per-form Attach step. The Meta card's per-form Attach button stays for forms Meta adds to the Page later.
**Track:** Ad Integrations
**Status:** COMPLETED
**Depends on:** Step 9 (per-form subscription model in place), Step 10 (schema + validation), Step 12 (frontend already reads `pipeline_stage`/mapping from subscription rows).

---

## Problem Step 13 fixes

Today's flow (post Step 9):

1. Owner clicks **Subscribe** on a Page.
2. Meta starts delivering `leadgen` webhooks for every form on that Page.
3. Worker looks up the form's subscription row — **not found** → DLQ.
4. Nothing shows up in the CRM's Leads list.
5. Owner has no idea. Support ticket.

Root cause: the "Attach" step is manual + hidden behind a form-list expand. Owners subscribe expecting leads to flow — that's the industry-standard mental model.

## Scope

In-scope:

- **New DAL helper `list_subscription_form_ids(integration_id) -> set[str]`** — pure lookup for the O(1) skip-check on re-subscribe. One statement, no business logic.

- **New service helper `auto_attach_forms(session, org_id, integration_id, forms)`** — for each form not already subscribed on this integration, upsert a subscription with:
  - `external_form_id`, `external_form_label` = as reported by the provider,
  - `field_mapping` = the output of `_default_mapping_for_questions(questions)` — heuristic maps `full_name`, `email`, `phone_number`, etc. to their CRM canonical keys,
  - `enabled = True`, `pipeline_stage = None` (org's default first stage).
  - Returns the count of newly-inserted rows for logging.
  - Idempotent — existing rows (with the operator's own edits) are never touched.

- **Heuristic `_default_mapping_for_questions`** — backend mirror of the frontend `field-mapping-editor` DEFAULT_RULES. Fields not matching any rule are omitted (worker will drop them at ingest, same effect as Ignore in the editor).

- **Meta router `subscribe_page_endpoint`** — after `upsert_page_token(...)`, call `list_lead_forms_for_page` (Page token already in hand) → hand the form list to `auto_attach_forms`. Failure of auto-attach must NOT roll back the Page subscription (leads still flow; operator can Edit Mapping later).

Out of scope:

- Google Ads parity — trivial follow-up once shape is settled, but Google's `subscribe form` flow is per-form already, so auto-attach is a no-op there.
- Auto-detect NEW forms Meta adds to an already-subscribed Page — the per-form Attach button on the Meta card handles this discoverably.
- Removing the per-form Attach button — kept as an escape hatch for forms discovered after the initial subscribe.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/integrations/data_access.py` | modified — add `list_subscription_form_ids` |
| `api/src/app/core/integrations/service.py` | modified — heuristic + `auto_attach_forms` helper |
| `api/src/app/core/integrations/meta/router.py` | modified — call `auto_attach_forms` after Page subscribe |
| `api/tests/test_integrations_status_and_mapping.py` | modified — 3 unit tests |
| `tasks/ad-integrations/step-9-frontend-meta-card-per-form-mapping.md` | modified — correct the stale "out of scope: auto-attach" note |

Five files, no schema change, no new endpoint.

## Verification

1. Fresh Meta connection, Page has 3 Lead Forms.
2. Owner clicks Subscribe.
3. Response 200 with `{"status": "subscribed", ...}` — same shape as before.
4. `tbl_integration_subscriptions` now contains 3 new rows, one per form, with `field_mapping = {"full_name": "contact.full_name", "email": "contact.email", "phone_number": "contact.phone", ...}` (whichever standard fields the form has).
5. A test leadgen submission via Meta Lead Ads Testing Tool → lead lands in Leads list within seconds. **No manual Attach click required.**
6. Re-Subscribe the same Page → no duplicate rows; existing operator edits on any form's mapping / `pipeline_stage` are preserved.

## Self-check

- ✅ 10 rules: no `/core → /packs`; `tbl_` naming preserved; layered architecture (DAL → service → router) followed; ≤10 files; no TODOs.
- ✅ Router → Service → DAL: router calls service; service calls DAL; DAL executes SQL; only service commits.
- ✅ Reuse: heuristic mirrors the frontend `DEFAULT_RULES` semantically (kept in sync as a comment reference — small enough to duplicate cleanly).
- ✅ Query efficiency: 1 query for existing form IDs + 1 batched INSERT for new rows; no N+1.
