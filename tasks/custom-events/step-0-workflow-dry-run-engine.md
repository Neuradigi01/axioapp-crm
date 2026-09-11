# Step 0 — Minimal `core/workflows/dry_run.py` engine (mini-track)

**Goal:** ship a minimal workflow dry-run engine so test-fire in Step 4/7c can render workflow actions WITHOUT side effects. Skip this step entirely if `core/workflows/dry_run.py` already exists with equivalent capability.
**Phase:** Custom Events track — step 0/17 (conditional)
**Depends on:** —
**Status:** Pending

## Scope

**In-scope (only if `core/workflows/dry_run.py` does NOT already exist):**
- New file `api/src/app/core/workflows/dry_run.py` exposing:
  ```python
  async def dry_run_workflow(
      session: AsyncSession,
      org_id: UUID,
      workflow_id: UUID,
      event_payload: dict,
      trigger_event_type: str,
  ) -> DryRunResult:
      """Walk the workflow graph; render each action's params via
      the templates renderer with the supplied payload; return
      a list of {action_type, would_do: str, rendered_params: dict}
      entries. Never invokes outbound channels."""
  ```
- `DryRunResult` schema: `{ actions: [{node_id, type, would_do, rendered_params, would_error?: str}], graph_reachability: dict }`.
- Handles the top action types:
  - `send_email`, `send_whatsapp`, `send_sms` → `would_do="Send [channel] to <resolved_recipient>: <subject>"`.
  - `update_field` → `would_do="Update <entity>.<field> to <rendered_value>"`.
  - `add_tag`, `remove_tag` → `would_do="Tag <rendered_tag>"`.
  - `create_task` → `would_do="Create task: <rendered_title>"`.
  - `wait` → `would_do="Wait <duration>"`.
  - `http_request` → `would_do="HTTP <method> <rendered_url>"` — **no actual request fired**.
  - `condition` → evaluate branch, log which branch taken.
  - `assign_owner` → `would_do="Assign to <resolved_user>"`.
- Never publishes to bus. Never writes to DB except a `tbl_workflow_dry_runs` audit row (optional; can defer to Step 7c which stores in `tbl_custom_event_test_runs`).
- Skips actions with `disabled=true`.

**Out of scope (defer if >3 days):**
- Full-fidelity condition evaluation (uses simple truthy checks).
- Loop / iteration constructs.
- Async wait resolution (treats waits as "would wait X").

## Files to touch
- `api/src/app/core/workflows/dry_run.py` (new).
- `api/src/app/core/workflows/schemas.py` (modified — add `DryRunResult`).
- `api/tests/test_workflows_dry_run.py` (new).

## Plan
1. **Verify prerequisite:** grep for `dry_run` in `core/workflows/`. If a working function exists that renders actions without side effects, **skip this step** and cite the existing function in Step 4/7c.
2. Implement `dry_run_workflow` using existing `core.variables.utils.resolve` as the renderer.
3. Test each action type.

## DB changes / migrations
None (audit rows deferred to Step 7c).

## Tests to add
- `test_dry_run_workflow_renders_send_email_without_actually_sending` — assert no email publisher called; result has `would_do` populated.
- `test_dry_run_workflow_evaluates_condition_and_takes_branch`.
- `test_dry_run_workflow_never_publishes_to_bus`.
- `test_dry_run_workflow_never_writes_to_side_effect_tables`.
- `test_dry_run_workflow_supports_custom_event_type` (uses a `custom.order.paid` payload).

## Verification checklist
- Backend: tests pass.
- Backend: manual `python -c "from src.app.core.workflows.dry_run import dry_run_workflow; ..."` on a seeded workflow.

## Self-check
- [ ] Rule 1: core only.
- [ ] Rule 2: no DB.
- [ ] Rule 8: ~3 files.
- [ ] Rule 10: no TODOs. If action types are added later they slot in additively.

## Stop & report
Await "proceed". If skipped (function already exists), report "SKIPPED — dry_run exists at <path>" and proceed to Step 1.
