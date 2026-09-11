# Step 6 — `tbl_variable_stale_refs` + custom-field delete/rename subscriber

**Goal:** when a custom field is deleted OR renamed OR type-changed, walk actual reference surfaces (templates body/subject/preview; workflow-versions.graph JSONB; chatbot-versions.graph JSONB; campaigns body/subject; automation action configs), write dedup'd stale-ref rows, expose them to Owner with dismiss.
**Phase:** Variables Unification track — step 6/13
**Depends on:** Steps 3, 4, 5
**Status:** Pending

## Scope

**In-scope:**
- Migration: `tbl_variable_stale_refs (id UUID PK, org_id UUID NOT NULL FK, source_entity_type TEXT NOT NULL, source_id UUID NOT NULL, source_channel TEXT, path TEXT NOT NULL, reason ENUM('deleted','renamed','type_changed'), detected_at TIMESTAMPTZ, resolved_at TIMESTAMPTZ NULL, resolved_by_user_id UUID NULL FK)`. Partial-unique index `UNIQUE (org_id, source_entity_type, source_id, path) WHERE resolved_at IS NULL`. RLS from migration one.
- Cascade triggers: on delete of `tbl_message_templates` / `tbl_workflows` / `tbl_chatbots` / `tbl_campaigns` / `tbl_automations` — soft-resolve their stale-refs (`resolved_at = NOW()`, `resolved_by_user_id = NULL`).
- `core/variables/stale_ref_detector.py` — Celery task `scan_for_stale_refs(org_id, custom_field_key, reason)`. Iterates surfaces:
  - `tbl_message_templates.body_text + .subject + .preview_text` (SQL: `WHERE org_id = ? AND (body_text LIKE ? OR subject LIKE ? OR preview_text LIKE ?)`).
  - `tbl_workflow_versions.graph JSONB` — text-search inside JSONB (Postgres `graph::text LIKE ?`).
  - `tbl_chatbot_versions.graph JSONB` — same.
  - `tbl_campaigns.body_text + .subject` (WhatsApp + Email; per project memory).
  - `tbl_automation_actions.config JSONB`.
- **Bulk-delete guard:** if `custom_field.deleted` bus events for one org exceed 100 within 60s, batch into one scan pass (Celery-queued, per-org rate-limited).
- Subscribers on `custom_field.deleted`, `custom_field.renamed` (new event), `custom_field.type_changed` (new event) events — publisher lives in `core/custom_fields/service.py`.
- Endpoints: `GET /api/v1/variables/stale-refs?resolved=false` (Owner-only, paginated) + `POST /api/v1/variables/stale-refs/{id}/resolve` (marks resolved + audit event).
- Auto-resolve on `template.saved` / `workflow.saved` / `chatbot.saved` / `campaign.saved` / `automation.saved` bus events — re-walk the specific row's tokens, resolve rows whose paths are no longer present.
- `core/custom_fields/service.py`: publish `custom_field.renamed` on key change (Step 3 didn't add rename endpoint; if renamable, needed here; if immutable, add a rename endpoint).

**Out of scope:**
- Frontend UI for the stale-refs pane (add in Step 8 or 9 wire-up if trivial, else follow-up).

## Files to touch
- `api/alembic/versions/NNNN_variable_stale_refs.py` (new).
- `api/src/app/core/variables/models.py` (modified — `StaleRef` model).
- `api/src/app/core/variables/stale_ref_detector.py` (new — Celery task + scan logic).
- `api/src/app/core/variables/router.py` (modified — 2 new endpoints).
- `api/src/app/core/variables/service.py` (modified — scan orchestration + dismiss).
- `api/src/app/core/variables/data_access.py` (modified — stale-ref DAL functions + scan queries).
- `api/src/app/core/custom_fields/service.py` (modified — publish `custom_field.renamed`, `custom_field.type_changed`, and existing `custom_field.deleted` events on bus).
- `api/src/app/core/events/event_catalog.py` (modified — register new event constants).
- Tests.

## Plan
1. Migration + `StaleRef` model.
2. Publisher hooks in custom-fields service.
3. Subscriber Celery task with per-surface scanners.
4. Bulk-delete debouncer (Redis counter + delayed dispatch).
5. Endpoints.
6. Auto-resolve subscribers on template/workflow/etc save events.
7. Cascade triggers.

## DB changes / migrations
Table creation + RLS enable + partial-unique index + FK cascades on referring tables (via ON DELETE triggers — polymorphic FK not feasible, use per-surface trigger).

## Tests to add
- `test_stale_ref_created_on_field_delete_walks_templates_workflows_chatbots_campaigns_automations`.
- `test_stale_ref_deduped_on_repeat_mutations_same_field`.
- `test_stale_ref_scan_runs_with_explicit_org_id_filter_not_rls_only` — RLS mocked off; scan still tenant-scoped.
- `test_stale_ref_cross_tenant_never_appears` — deleting field in org A never writes rows referencing org B templates.
- `test_stale_ref_bulk_delete_batches_into_one_scan_pass` — 200 delete events → 1 scan invocation.
- `test_stale_ref_dismiss_endpoint_marks_resolved_with_audit_event`.
- `test_stale_ref_auto_resolve_on_template_saved_when_token_removed`.
- `test_stale_ref_cascades_on_referring_row_delete` — delete template → row auto-resolved.
- `test_stale_refs_endpoint_owner_only_paginated`.

## Verification checklist
- Backend: all tests pass.
- Backend: migration up + down clean.
- Backend: create a custom field, insert `{{contact.custom.foo}}` in a template, delete the field, `GET /variables/stale-refs` returns row.
- Backend: dismiss endpoint updates row + emits audit.

## Self-check
- [ ] Rule 1: core only.
- [ ] Rule 2: `tbl_variable_stale_refs` has `org_id` + RLS.
- [ ] Rule 3: reads custom_fields — doesn't modify.
- [ ] Rule 4: N/A.
- [ ] Rule 5: N/A.
- [ ] Rule 6: 1 new perm `variables.stale_refs.manage` (Owner-only) — registered in permissions registry.
- [ ] Rule 7: N/A.
- [ ] Rule 8: ~10 files — at limit. Sub-split if implementation grows (auto-resolve could be its own step).
- [ ] Rule 9: stop and report.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
