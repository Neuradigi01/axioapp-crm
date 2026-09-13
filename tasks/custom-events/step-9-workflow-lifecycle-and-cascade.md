# Step 9 — Workflow lifecycle: soft-delete auto-disables, re-activation prompt, schema-removal review flag, extended contact-merge cascade

**Goal:** wire the lifecycle rules: soft-deleting a custom event disables dependent workflows with audit; re-activation shows an Owner prompt (does NOT auto-re-enable); schema-key removal flags dependent workflows/templates for review; contact-merge cascade extended to occurrences + archive.
**Phase:** Custom Events track — step 9/17
**Depends on:** Steps 6, 7c, 8
**Status:** Pending

## Scope

**In-scope:**
- `core/public_ingest/custom_events/service.py`:
  - **On soft-delete:** find all workflows whose trigger `event_type == add_prefix(event.name)`; set `workflow.is_active=false`; emit audit `custom_event.deleted.workflow_disabled` per workflow.
  - **On re-activation:** find previously-disabled workflows whose trigger still matches this event AND whose `trigger_event_type` HASN'T been moved to another event since disable; return list to caller. Owner-only endpoint `POST /custom-events/{id}/reactivate-workflows` batch-enables. Prompt logic lives in the frontend.
  - **On schema edit that REMOVES a payload key:** walk dependent workflows/templates for `{{event.<removed_key>}}` references (reuse Track A Step 6's `stale_ref_detector.py` scan surfaces). Write `tbl_variable_stale_refs` rows with `reason='deleted'`, `source_channel='event_payload'`. Publish `custom_event.schema.key_removed` bus event with the workflow-review action. Workflow marked "needs review" (`review_needed_at` column on `tbl_workflows` — added below), NOT auto-disabled.
- Migration: add `tbl_workflows.review_needed_at TIMESTAMPTZ NULL` (soft indicator).
- `core/contacts/merge_service.py` cascade table list extended:
  - `tbl_custom_event_occurrences` → repoint `contact_id`.
  - `tbl_custom_event_occurrences_archive` → repoint `contact_id`.
  - `tbl_custom_event_test_runs` → no-op (dry-run data; no contact repointing needed).
- `core/contacts/service.delete_contact_service()` cascade: null `contact_id` in occurrences + archive (already `ON DELETE SET NULL` per FK definition — verify test).

**Out of scope:**
- Frontend prompt rendering (Step 14).
- Retention jobs (Step 10).

## Files to touch
- `core/public_ingest/custom_events/service.py` (modified — lifecycle hooks).
- `core/public_ingest/custom_events/router.py` (modified — reactivate-workflows endpoint).
- `core/workflows/models.py` (modified — `review_needed_at` column).
- `api/alembic/versions/NNNN_workflow_review_needed_at.py` (new migration).
- `core/contacts/merge_service.py` (modified — cascade list).
- `core/variables/stale_ref_detector.py` (modified — accept `source_channel='event_payload'` for schema-key removal).
- Tests.

## Plan
1. Migration for `review_needed_at`.
2. Soft-delete hook: find + disable workflows.
3. Re-activation prompt endpoint.
4. Schema-key-removal walk (reuses stale-ref detector).
5. Contact-merge cascade extension.
6. Tests.

## DB changes / migrations
Add `tbl_workflows.review_needed_at TIMESTAMPTZ NULL`.

## Tests to add
- `test_custom_event_soft_delete_disables_all_dependent_workflows_with_audit`.
- `test_custom_event_reactivation_returns_previously_disabled_workflows_whose_trigger_still_matches`.
- `test_custom_event_reactivation_excludes_workflows_whose_trigger_moved_to_another_event`.
- `test_custom_event_reactivation_does_not_auto_enable_owner_confirms`.
- `test_custom_event_schema_key_removal_flags_workflows_review_needed`.
- `test_custom_event_schema_key_removal_writes_stale_ref_rows`.
- `test_custom_event_schema_key_removal_does_not_auto_disable_workflows`.
- `test_contact_merge_repoints_custom_event_occurrences`.
- `test_contact_merge_repoints_custom_event_occurrences_archive`.
- `test_contact_delete_nulls_occurrence_contact_id_via_fk_cascade`.
- `test_workflow_run_evaluates_event_active_at_step_boundary` — race between soft-delete and in-flight workflow (workflow executor re-checks `event.is_active` before outbound-channel steps).

## Verification checklist
- Backend: all tests pass.
- Backend: migration up + down clean.
- Backend: manual: create custom event, workflow, delete event → workflow disabled + audit + reactivate flow works.

## Self-check
- [ ] Rules 1, 2 clean.
- [ ] Rule 8: 7 files.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
