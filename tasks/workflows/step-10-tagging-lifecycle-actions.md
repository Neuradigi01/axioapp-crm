# Step 10 — Tagging + lifecycle actions

**Goal:** Register the tagging + segmentation + lifecycle action handlers — add/remove tag, add/remove from saved list, set lead score, mark converted, mark unsubscribed, block (DND), archive, enroll in another workflow, enroll in a sequence, remove from a sequence.
**Status:** COMPLETED — NEW `core/workflows/actions/tagging.py` registers 5 handlers: `tagging.add_tag` patches `Contact.tags` via `contacts.service.update_contact` (idempotent — re-adding the same tag returns `added=False`); `tagging.remove_tag` is silent on missing (returns `removed=False`); `tagging.add_to_list` + `tagging.remove_from_list` raise `ActionNotImplemented` (the contacts.groups module is filter-based — no manual membership table); `tagging.set_lead_score` supports set/increment/decrement on `Lead.lead_score` (clamped to [0,100] per the model's documented bounds), and when the score crosses the operator-supplied threshold (default 75) emits `lead.score_threshold` on the events bus with a deterministic `event_id=lead_score_threshold:{lead_id}:{threshold}:{direction}` so re-triggered workflows dedupe cleanly. NEW `core/workflows/actions/lifecycle.py` registers 8 handlers: `lifecycle.mark_converted` flips `Lead.status='won'` (the closest the v1 LeadStatus enum offers — `converted` would need an enum extension); `lifecycle.mark_unsubscribed` flips `Contact.email_opt_out=True` + stamps `email_opt_out_at`; `lifecycle.block_contact` + `lifecycle.archive_contact` raise `ActionNotImplemented` (no DND table + no `archived_at` column on Contact yet); `lifecycle.enroll_in_workflow` reads the target workflow + enforces its `re_enrollment_rule` via the same `find_existing_run` dedupe path the bus subscriber uses (`once` / `daily` rules), refuses non-active targets via `skip_reason='validation_failed'`, then calls `engine.start_run` with the parent run's contact_id + shallow-copied trigger payload + `event_id=workflow_enrol:{parent_run_id}:{target_id}`; `lifecycle.enroll_in_sequence` calls `email_sequences.service.enroll`; `lifecycle.remove_from_workflow` marks all `(workflow_id, contact_id)` runs in `pending`/`running` as `canceled` + sets `outcome='canceled'` + clears `current_node_id`; `lifecycle.remove_from_sequence` calls `email_sequences.service.cancel_enrollment` against an `enrollment_id` from a prior step's output. Every handler shares the standard skip-reason mapping (HTTPException 401/403 → permission_denied, 404 → target_not_found, 400/409/422 + ValidationError → validation_failed). Variable resolution on every string-typed config field (e.g. `tag: '{{ contact.tier }}-customer'`) via `core.templates.variables.resolve`. `core/workflows/__init__.py` extended with side-effect imports of both modules. 10 pytest cases in `test_tagging_actions.py`: add_tag happy + idempotent; remove_tag silent on missing + present-case removes correctly; set_lead_score set/increment/decrement with clamp-at-zero; threshold-crossing publishes the `lead.score_threshold` event; add_to_list + remove_from_list raise `ActionNotImplemented`. 8 pytest cases in `test_lifecycle_actions.py`: mark_converted flips Lead.status to won; mark_unsubscribed sets email_opt_out + email_opt_out_at; enroll_in_workflow creates a new run with parent's contact_id; enroll_in_workflow dedupes under `once` rule via prior-run check; enroll_in_workflow refuses non-active target with `validation_failed`; remove_from_workflow cancels exactly the `pending`+`running` runs (leaves completed alone); block_contact + archive_contact raise `ActionNotImplemented`. Pytest run deferred per `feedback_pause_before_pytest.md`. No migration needed — all writes go through existing schemas.

**Spec deviation**: Several handlers ship as `ActionNotImplemented` placeholders because the underlying modules don't exist yet — `tagging.add_to_list` / `remove_from_list` (contacts.groups is filter-based, no manual membership table), `lifecycle.block_contact` (no tbl_block_list), `lifecycle.archive_contact` (no archived_at column). The spec also referenced `leads.scoring.service.adjust_score` (only `recompute_lead` exists) and a dedicated `convert_lead` (LeadStatus enum only has active/won/lost in v1); both are routed through `leads.service.update_lead` with the closest-equivalent column writes. Future tracks that ship the missing modules will replace the placeholder bodies without touching the action-type registration.
**Depends on:** Step 4 (engine + action contract). `core/contacts/groups/` (saved lists), `core/leads/scoring/`, `core/contacts/consent/` (opt-out), `core/contacts/block_list/` (DND), Step 4 of this track for sub-workflow enrollment.

---

## Scope

In-scope:

- `core/workflows/actions/tagging.py` registering:

  **Tagging:**
  - `tagging.add_tag` — node config: `{tag: 'vip' | '{{rendered}}', target: 'contact' | 'lead'}`. Idempotent (re-adding the same tag is a no-op).
  - `tagging.remove_tag` — same shape.

  **List membership:**
  - `tagging.add_to_list` — node config: `{group_id: UUID}`. Calls `contacts.groups.service.add_member(...)`.
  - `tagging.remove_from_list` — same.

  **Scoring:**
  - `tagging.set_lead_score` — node config: `{operation: 'set' | 'increment' | 'decrement', value: int}`. Calls `leads.scoring.service.adjust_score(...)`. Crossing a configured threshold (e.g. ≥75) emits `lead.score_threshold` which can re-trigger other workflows.

- `core/workflows/actions/lifecycle.py` registering:

  **Lifecycle:**
  - `lifecycle.mark_converted` — flips `lead.status='converted'` + promotes lead → contact if not already. Calls `leads.service.convert_lead(...)`.
  - `lifecycle.mark_unsubscribed` — flips `contact.marketing_consent='opted_out'` + writes a `tbl_opt_in_consent_events` row via `consent.service.opt_out(...)`.
  - `lifecycle.block_contact` — adds to `tbl_block_list` (DND). All future workflow Send actions check this list via Step 12's compliance gates.
  - `lifecycle.archive_contact` — soft archive (sets `archived_at`); contact stops showing in default views.

  **Sub-workflows:**
  - `lifecycle.enroll_in_workflow` — node config: `{workflow_id: UUID}`. Calls `engine.start_run(...)` for the target workflow with the same `contact_id` + a shallow-copied trigger payload. Honors the target workflow's re-enrollment rule.
  - `lifecycle.enroll_in_sequence` — node config: `{sequence_id: UUID}`. After Step 20 absorbs email_sequences into workflows, this becomes a thin wrapper around `enroll_in_workflow` (sequence = linear workflow); until then, it calls `email_sequences.service.enroll(...)`.
  - `lifecycle.remove_from_workflow` / `lifecycle.remove_from_sequence` — pause/cancel the contact's run in the target workflow/sequence.

- All handlers go through the origin module's service so audit + permission + custom-field validation fire correctly. Same skip-reason mapping as Step 8 (permission_denied / target_not_found / validation_failed).

- Output: each handler's `ActionResult.output` carries the relevant ids + new state for downstream context. E.g. `lifecycle.mark_converted` outputs `{contact_id: UUID, new_lead_status: 'converted', conversion_recorded_at: '...'}`.

Out of scope:

- "Add to multiple lists at once" — operator chains nodes.
- Custom-field-driven dynamic tag names — already supported via template variables in the tag string config.
- Bulk un-enrollment ("remove every contact from sequence X") — workflows are per-contact; bulk is admin-only.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/workflows/actions/tagging.py` | **NEW** |
| `API/src/app/core/workflows/actions/lifecycle.py` | **NEW** |
| `API/src/app/core/workflows/actions/__init__.py` | edit — side-effect import both |
| `API/tests/workflows/test_tagging_actions.py` | **NEW** |
| `API/tests/workflows/test_lifecycle_actions.py` | **NEW** |

**~5 files. ~400 lines.**

## Plan

1. Tagging handlers — 5 handlers, each thin wrapper over the origin service.
2. Lifecycle handlers — 8 handlers, same shape.
3. Action registry side-effect imports.
4. Tests — happy paths + skip-reason coverage + sub-workflow enrollment honors re-enrollment rules.

## DB changes / migrations

None.

## Tests

15 pytest cases:

- Tagging: add_tag idempotent; remove_tag silent on missing; add_to_list writes membership row; set_lead_score increments/decrements/sets correctly; crossing threshold emits `lead.score_threshold`.
- Lifecycle: mark_converted flips status + promotes; mark_unsubscribed writes consent_event; block_contact adds to DND; archive_contact sets archived_at; enroll_in_workflow honors target's re-enrollment rule; enroll_in_sequence calls sequences.service.enroll; remove_from_workflow pauses the run.
- Skip-reason coverage for the three error categories on each handler family.

## Smoke

```
1. Workflow: trigger(quote.accepted) → tagging.add_tag(tag='customer') → lifecycle.mark_converted →
   lifecycle.enroll_in_workflow(workflow_id=<NewCustomerWelcome>).
2. publish quote.accepted with {contact_id: ..., quote_id: ...}.
3. SELECT * FROM tbl_contacts → tags contains 'customer'; status='converted'.
4. SELECT * FROM tbl_workflow_runs WHERE workflow_id=<NewCustomerWelcome> → new run started.
5. publish lead.score_threshold (fired by set_lead_score crossing 75) → other workflows triggered.
```

## Risks

- Sub-workflow enrollment loop — workflow A enrolls contact in workflow B which enrolls contact back in A. Mitigation: Step 19 adds an execution-depth counter to the run state; depth > 5 → run skipped with `skip_reason='enrollment_loop_detected'`.
- Removing a contact from a sequence mid-flight = abrupt cut. UX preference (from manager's HubSpot reference): preserve the audit trail by marking sequence-run `canceled` instead of deleting.
- Tag string with empty variable resolution (e.g. `{{ contact.tier }}` when contact has no tier) renders as empty string → empty tag refused at validate-time. Skip_reason='validation_failed'.

## Self-check (10 rules)

`core/workflows/actions/`. ✓ org_id-scoped via engine RLS. ✓ Custom fields supported transparently (tag rendering). ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions enforced through origin services. pack.yaml untouched. ✓ 5 files / ~400 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 10 — Tagging + lifecycle actions
Files: 5
Verify: 5 tagging + 8 lifecycle handlers operational; sub-workflow enrollment honors target re-enrollment rule; lead.score_threshold emits on threshold cross.
Tests: 15 pytest cases.
Awaiting "proceed".
```
