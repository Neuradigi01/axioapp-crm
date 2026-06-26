# Step 4 — Execution engine + Celery step processor

**Goal:** The heart of workflows. Wire the engine that walks a workflow graph step-by-step on behalf of an enrolled contact — pull current node from the run row, resolve the action handler from the registry, execute, schedule the next node (via Celery `eta` for waits, immediate for everything else), persist a step-run audit row, repeat until terminal.
**Status:** Pending
**Depends on:** Step 1 (run + step_run tables). Step 2 (service exposes `get_workflow` + graph access). Step 3 (router — not strictly required but the engine emits run rows the router exposes).

---

## Scope

In-scope:

- `core/workflows/engine.py`:
  - `async start_run(session, *, workflow: Workflow, contact_id: UUID | None, trigger_event_id: str | None, trigger_payload: dict) -> WorkflowRun` — inserts a run row in `status='pending'` pointed at the trigger node, then calls `schedule_next_step(...)` which either dispatches Celery immediately OR sets `next_step_at` for a delay node. Step 5's trigger-handlers call this.
  - `async process_step(run_id: UUID)` — Celery task body. Loads the run + workflow + current node + step_run, runs the action handler, persists outcomes, advances to the next node, recurses (via Celery enqueue, never inline) until a wait/terminal/branch.
  - `async resume_after_wait(run_id: UUID)` — beat-driven; pulls runs whose `next_step_at <= now()` and re-dispatches `process_step`. Same shape as the scheduled-campaigns sweep.
  - Internal: `_advance(run, executed_step_run, output_edge_label=None)` — picks the next node from the graph using the edge label (for branch / switch / ab_split), or the single outbound edge for sequential nodes, or terminates the run when no outbound edges. Terminal sets `run.status='completed'` + `run.outcome='completed'` (or `goal_reached` if the executed node was the goal node).
  - Error handling: any action handler raising is caught, logged, written to `step_run.error`, and the run is set to `status='errored'`. Operator sees it in the run-history UI (Step 19). Configurable retry policy is deferred — v1 errors are terminal.

- Action handler contract (referenced by Steps 7-11):
  - `async def handle(session: AsyncSession, *, run: WorkflowRun, step_run: WorkflowStepRun, node: dict, context: dict) -> ActionResult` where `ActionResult = {next_edge_label: str | None, output: dict | None, skip_reason: str | None}`. `node['config']` carries the operator's per-node config. `context` carries `{contact, trigger_payload, run_state}` for variable resolution.

- Celery tasks in `core/workflows/tasks.py`:
  - `workflows.process_step(run_id)` — calls `engine.process_step`.
  - `workflows.sweep_waits()` — beat-driven; calls `engine.resume_after_wait`. Wired into `celery_config.beat_schedule` at `crontab(minute='*/1')` (60s cadence — the same cadence email-sequences uses).
  - Celery-absent shim mirroring `core/integrations/whatsapp/health_tasks.py`.

- `core/workflows/data_access.py` extended:
  - `insert_run` / `insert_step_run` — stage-only.
  - `get_run_for_processing(session, *, run_id)` — locked read (`SELECT ... FOR UPDATE SKIP LOCKED` against `tbl_workflow_runs`) so two workers can't process the same run twice.
  - `list_runs_due_for_resume(session, *, limit)` — `WHERE status='pending' AND next_step_at <= now()` for the sweep.
  - `list_runs(session, *, org_id, workflow_id=None, contact_id=None, status=None, limit, offset)` — drives Step 19's run-history endpoint.
  - `list_step_runs(session, *, org_id, run_id)` — drives the per-run step timeline.

- `core/workflows/router.py` extended:
  - `GET /workflows/{id}/runs?status=&limit=&offset=` — `workflows.read`.
  - `GET /workflows/runs/{run_id}` — `workflows.read`.
  - `GET /workflows/runs/{run_id}/steps` — `workflows.read`.

- A built-in `trigger` action handler (the entry node) — does nothing but logs the enrollment + advances; registered in `actions/__init__.py` so the engine doesn't need a special case for the trigger node.

Out of scope:

- Real action handlers (Steps 7-11).
- Wait / branch / switch / goal handlers (Step 11).
- Trigger subscriptions (Step 5).
- Conditions (Step 6).
- Compliance gates (Step 12).
- UI (Steps 13+).
- Retry / DLQ policy beyond "first error is terminal".

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/workflows/engine.py` | **NEW** |
| `API/src/app/core/workflows/tasks.py` | **NEW** |
| `API/src/app/core/workflows/data_access.py` | edit — extend with run + step_run helpers |
| `API/src/app/core/workflows/router.py` | edit — 3 new run/step-history endpoints |
| `API/src/app/core/workflows/actions/__init__.py` | edit — register built-in `trigger` action |
| `API/src/celery/celery_config.py` | edit — `workflows-sweep-waits` beat entry |
| `API/src/celery/worker.py` | edit — autodiscover `src.app.core.workflows.tasks` |
| `API/tests/workflows/test_engine.py` | **NEW** |
| `API/tests/workflows/test_engine_persistence.py` | **NEW** |

**~9 files. ~700 lines.** Above the ~400-line guideline because the engine + Celery wiring + run-history endpoints + persistence tests all need to land together to be testable.

## Plan

1. DAL extensions first (engine + tests both depend).
2. Engine — `start_run`, `process_step`, `_advance`, `resume_after_wait`.
3. Action-registry built-in `trigger` handler.
4. Celery task wrappers + beat entry + autodiscover.
5. Router run-history endpoints.
6. Tests: simulate a linear workflow + assert step_runs land in order + run terminates correctly; wait node parks + sweep resumes; error in handler → run errored + step_run.error populated.

## DB changes / migrations

None — uses tables from Step 1.

## Tests

12 pytest cases:

- `start_run` inserts a run + the first step_run (for the trigger node).
- `process_step` advances trigger → action → terminal.
- Two-node workflow (trigger → fake send): step_runs land with monotonic step_index 0, 1.
- Branch node with two labeled edges: handler returns `next_edge_label='yes'` → advance picks the yes edge.
- Wait node sets `run.next_step_at` to future, `status='pending'`; `process_step` returns without recursing.
- `sweep_waits` picks up a run whose `next_step_at <= now()` and dispatches.
- Action handler raises → run.status='errored', step_run.error contains traceback.
- `FOR UPDATE SKIP LOCKED` actually serializes: two concurrent `process_step` calls for the same run — only one proceeds, the other skips.
- Goal node terminal: `run.outcome='goal_reached'`.
- Non-existent action_type in a node → run errored with `ActionNotRegistered` reason.
- `GET /workflows/{id}/runs` returns the paginated list.
- `GET /workflows/runs/{run_id}/steps` returns the ordered step_runs.

## Smoke

```
1. Create a workflow with: trigger(event_type='lead.created') → goal node.
2. Activate it.
3. Python shell: await engine.start_run(workflow, contact_id=..., trigger_payload={}).
4. Wait ~5s for the Celery task to run.
5. SELECT * FROM tbl_workflow_runs → status='completed', outcome='goal_reached'.
6. SELECT * FROM tbl_workflow_step_runs → 2 rows (trigger + goal), both completed.
```

## Risks

- Celery `eta` for waits has worker-clock skew implications — under heavy load a 60s wait could fire 60-90s late. Acceptable for v1; document in engine.py docstring.
- `FOR UPDATE SKIP LOCKED` on the runs row needs index coverage; partial index from Step 1 covers it.
- Long-wait runs (e.g. 7-day wait) hold an open run row indefinitely. If the workflow is archived mid-wait, the engine sees `status='archived'` and terminates the run as `canceled`.
- Recursion via Celery enqueue (not in-process) means tail-latency per step ~= worker scheduling latency ~= seconds. For workflows that need <100ms hops, this is too slow — but at the manager's spec'd use cases (marketing nurtures), per-hop latency doesn't matter.

## Self-check (10 rules)

`core/workflows/` + small `celery_config.py` + `worker.py` edits. ✓ org_id-scoped via RLS. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions enforced on the new endpoints. ✓ pack.yaml untouched. ✓ 9 files / ~700 lines — over but justified. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 4 — Execution engine + Celery step processor
Files: 9
Verify: linear workflow walks trigger→goal cleanly; wait node parks + sweep resumes; handler errors persist as run.status='errored'; run-history endpoints live.
Tests: 12 pytest cases.
Awaiting "proceed".
```
