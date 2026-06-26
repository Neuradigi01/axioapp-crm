# Step 11 — Flow control (wait / if-else / switch / A/B split / goal / wait-for-event / webhook / internal)

**Goal:** Register the flow-control action handlers — the structural nodes that shape how a workflow walks. Wait (fixed delay), if/else (binary branch), switch (multi-way), A/B split (random 50/50), goal node (run-terminator with `outcome=goal_reached`), wait-for-event (park until a specific event fires for this contact, OR timeout), call webhook (HTTP POST out), notify user (in-app notification).
**Status:** Pending
**Depends on:** Step 4 (engine + wait-node parking). Step 6 (`branch` + `switch` handlers already partially shipped — this step adds the rest). Step 5 (event-bus subscriptions — `wait_for_event` reuses the same subscription mechanism to resume).

---

## Scope

In-scope:

- `core/workflows/actions/flow_control.py` extended with:

  **Wait:**
  - `flow_control.wait` — node config: `{duration_seconds: int, max_seconds: int (cap 30 days)}`. Sets `run.next_step_at = now + duration` + `run.status='pending'`. Step 4's beat sweep resumes it.

  **A/B split:**
  - `flow_control.ab_split` — random 50/50 (or weighted via `{weights: [60, 40]}`). Returns `next_edge_label='a'` or `'b'`. Uses Python's `random.random()` seeded with `(run.id, node.id)` so re-runs deterministically pick the same branch — avoids inconsistent test cases + makes diagnostics reproducible.

  **Goal:**
  - `flow_control.goal` — marker action. Returns `next_edge_label=None` so the engine treats the run as completed; sets `run.outcome='goal_reached'`. Used by Step 19's analytics for goal-conversion math.

  **Wait-for-event:**
  - `flow_control.wait_for_event` — node config: `{event_type: 'email.opened' | 'whatsapp.message_received' | ..., max_wait_seconds: int (cap 30 days), contact_match: bool (default true)}`. Sets `run.status='pending'` + writes a `tbl_workflow_event_waits` row carrying `(run_id, node_id, event_type, contact_id, expires_at)`. The trigger-handlers module (Step 5) — when an event fires — looks up matching wait rows and resumes the relevant runs. On timeout, the beat sweep resumes the run on the `timeout` outbound edge (validator enforces presence).

  **External:**
  - `flow_control.call_webhook` — node config: `{url, method, body_template, headers, expected_status_codes}`. POSTs the rendered body to the URL with auth headers. Failure (non-2xx, timeout, DNS error) is per-config: either skip the step (default) or fail the run.
  - `flow_control.notify_user` — sends an in-app notification via `core/notifications/service.notify(...)` to a configured user (workflow owner / lead.owner / specific_user). Useful for "alert sales rep when a hot lead replies" patterns.

  **Internal:**
  - `flow_control.log_internal_note` — adds an internal-only note to the contact's timeline (visible only to operators, not the customer). Same as `record.create_note` but flagged `is_internal=true`.

- New table `tbl_workflow_event_waits`:
  - `id`, `org_id`, `run_id` CASCADE, `node_id`, `event_type`, `contact_id` nullable, `expires_at`. Indexes: `(org_id, event_type, contact_id) WHERE expires_at > now()` (resume-lookup); `(expires_at) WHERE expires_at > now()` (sweep target).
  - Step 5's trigger-handler module checks this table on every event publish; matches → resume the run on the corresponding output edge (`event_received`).

- `core/workflows/data_access.py` extended:
  - `find_waits_for_event(session, *, org_id, event_type, contact_id) -> list[WorkflowEventWait]`.
  - `expire_waits_due(session, *, batch_limit=200) -> list[WorkflowEventWait]` — beat-driven, returns expired waits + cleans them up.
  - `delete_wait(session, *, wait_id)` — called after a resume so the same wait doesn't fire twice.

- Engine extension: `engine.resume_run(run_id, output_edge_label)` — public entrypoint trigger-handlers + beat sweep use to wake a parked run on a specific edge.

- The trigger-handler module's universal `_on_event` also checks `find_waits_for_event` and resumes matching runs.

Out of scope:

- "Loop until goal" patterns — v1 doesn't allow back-edges except for wait-for-event's timeout fallback (which is one-shot). True loops are deferred.
- Stochastic timing ("wait between 1h and 4h randomly") — operators string a wait + a branch on `random()` if needed.
- Webhook retries — first failure is terminal in v1; retries are a polish step.

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_workflow_event_waits.py` | **NEW** — table + indexes + RLS |
| `API/src/app/core/workflows/models.py` | edit — `WorkflowEventWait` model |
| `API/src/app/core/workflows/schemas.py` | edit — `EventWaitRead` |
| `API/src/app/core/workflows/data_access.py` | edit — wait helpers |
| `API/src/app/core/workflows/engine.py` | edit — `resume_run` entrypoint |
| `API/src/app/core/workflows/trigger_handlers.py` | edit — resume waits on every event |
| `API/src/app/core/workflows/actions/flow_control.py` | edit — wait + ab_split + goal + wait_for_event + call_webhook + notify_user + log_internal_note |
| `API/src/app/core/workflows/tasks.py` | edit — `expire_waits` Celery task |
| `API/src/celery/celery_config.py` | edit — `workflows-expire-waits` beat entry at `crontab(minute='*/2')` |
| `API/tests/workflows/test_flow_control.py` | **NEW** |
| `API/tests/workflows/test_wait_for_event.py` | **NEW** |

**~11 files. ~700 lines.** Above the ~400 guideline because wait-for-event is structurally distinct from the other handlers and needs its own table + beat sweep.

## Plan

1. Migration: `tbl_workflow_event_waits` + RLS + indexes.
2. Model + schema + DAL.
3. Engine `resume_run` entrypoint + trigger-handler wait-table check.
4. Flow-control handlers (7 new — wait / ab_split / goal / wait_for_event / call_webhook / notify_user / log_internal_note).
5. Beat sweep for expired waits.
6. Tests: each handler operates correctly; wait_for_event parks + matching event resumes on `event_received`; timeout resumes on `timeout`; the table is properly cleaned post-resume.

## DB changes / migrations

One new table `tbl_workflow_event_waits` + RLS + 2 indexes. Reversible.

## Tests

15 pytest cases:

- `wait` parks run + sets `next_step_at`.
- `ab_split` deterministic per `(run_id, node_id)` seed.
- `ab_split` honors weighted config.
- `goal` terminates run with `outcome='goal_reached'`.
- `wait_for_event` inserts a wait row + parks run.
- Matching event resumes run on `event_received` edge + deletes wait row.
- Timeout resumes run on `timeout` edge + deletes wait row.
- Non-matching event (different contact) doesn't resume.
- `call_webhook` happy: 2xx response → step completes.
- `call_webhook` 5xx: skip_reason='webhook_failed' OR errored per config.
- `notify_user` posts to notifications.
- `log_internal_note` writes timeline entry.
- Beat sweep collects expired waits + dispatches resume tasks.
- Engine.resume_run handles unknown edge label (defensive — engine logs + errors run).
- Wait row CASCADE-deleted when the parent run is canceled.

## Smoke

```
1. Workflow: trigger(quote.sent) → wait(2 hours) → send.email("did you see the quote?")
   → wait_for_event(event_type=quote.viewed, max_wait_seconds=7 days)
     → on event_received: send.email("Glad you saw it") → goal node.
     → on timeout: send.whatsapp("just checking on the quote") → goal node.
2. publish quote.sent → run parks after the 2h wait → email sent on resume → run parks at wait_for_event.
3. publish quote.viewed for the same contact within 7 days → wait resumes → final email sent → goal.
4. OR no quote.viewed for 7 days → beat sweep expires wait → WhatsApp fallback → goal.
```

## Risks

- Wait rows live indefinitely if the beat sweep stops — mitigation: include a `created_at` index; alerts at >100K expired-but-still-present rows.
- Race: event published exactly at expires_at — both the matching path AND the timeout path could fire. Mitigation: the trigger-handler's resume check uses `expires_at > now()` so a hair-late event no-ops; the sweep then fires the timeout edge. Idempotent on the engine side (one resume per wait).
- Webhook URL contains a secret token — same handling as Slack URL from Step 7: prefer org-stored encrypted credentials over inline node config.

## Self-check (10 rules)

`core/workflows/`. ✓ org_id-scoped on tbl_workflow_event_waits with RLS. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions enforced via origin services for notify_user. pack.yaml untouched. ✓ 11 files / ~700 lines — over but justified (new table + multi-handler step). Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 11 — Flow control (wait / if-else / switch / A/B / goal / wait-for-event / webhook / internal)
Files: 11
Verify: 10 flow-control handlers operational; wait-for-event parks correctly; matching event resumes on event_received edge; timeout resumes on timeout edge.
Tests: 15 pytest cases.
Awaiting "proceed".
```
