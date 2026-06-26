# Step 2 — Workflow service + graph validator

**Goal:** CRUD service for workflows (create / get / list / patch / archive) + a graph validator that rejects malformed DAGs (cycles, orphan nodes, missing trigger, missing template references, dangling edges). Service writes versions on every publish; folder CRUD ships with it.
**Status:** Pending
**Depends on:** Step 1 (schema + models + action registry stub).

---

## Scope

In-scope:

- `core/workflows/data_access.py` extended:
  - `get_workflow(session, *, org_id, workflow_id)`.
  - `list_workflows(session, *, org_id, status=None, category=None, folder_id=None, q=None, limit=50, offset=0)` returning `(rows, total)`. Tenant-auto-filter + explicit `org_id` belt.
  - `list_folders(session, *, org_id)`.
  - `get_folder(session, *, org_id, folder_id)`.
  - `add_workflow / add_version / add_folder` — stage-only helpers (no commits — service commits).

- `core/workflows/service.py`:
  - `create_workflow(session, *, org_id, user_id, payload: WorkflowCreate) -> Workflow` — validates graph via `validate_graph(...)`, persists in `status='draft'`, writes a v1 row in `tbl_workflow_versions`, commits. RLS-context-aware via the `do_orm_execute` listener.
  - `get_workflow(session, *, org_id, workflow_id) -> Workflow` — raises `WorkflowNotFound` on miss.
  - `list_workflows(...)` — passthrough to DAL.
  - `update_workflow(session, *, org_id, user_id, workflow_id, payload: WorkflowUpdate) -> Workflow` — re-validates graph if `graph` is in the patch. Bumps `current_version`, writes a new version row. Rejects edits when `status='active'` AND `is_marketing=true` (locks active marketing workflows behind a "Pause first" workflow — same pattern as templates' published-lock). Operator can pause + edit + reactivate (workflows aren't immutable like email templates — they're built to evolve).
  - `change_status(session, *, org_id, user_id, workflow_id, new_status) -> Workflow` — transitions through the lifecycle (`draft → active`, `active ↔ paused`, anything → `archived`). Activating runs a final `validate_graph(...)` so a draft can't go live broken. Step 12's compliance pre-flight also fires here so a marketing workflow without a configured opt-out path can't activate.
  - `archive_workflow(...) ` — soft archive (no row delete). Outstanding runs continue under the archived version (immutable history).
  - Folder CRUD: `create_folder / list_folders / patch_folder / delete_folder` (the last refuses when the folder still has workflows; surfaces a 409 with the count).
  - All commits in `service.py`; DAL has no commits.

- `core/workflows/graph.py` — graph validator (pure helper, no DB):
  - `validate_graph(graph: WorkflowGraph) -> None`. Raises `InvalidGraph(reason: str)`. Checks:
    - Exactly one node of `type='trigger'` (workflows need an entry point; A/B-split sibling workflows still each have their own trigger).
    - Trigger node carries a non-empty `event_type` string in its config.
    - Every edge references existing node ids (`source` + `target` both in the node set).
    - No cycles (Kahn's algorithm — Step 11's wait-for-event nodes can loop back to themselves but only via the `timeout` edge, not the resume edge; validator special-cases that single back-edge).
    - No orphan nodes (every non-trigger node is reachable from the trigger).
    - Goal node, when set, exists in the node set.
    - Send-action nodes that reference `template_id` resolve to a real `tbl_message_templates` row in the org (this check needs the session — `validate_graph_with_db(session, org_id, graph)` is the variant the service calls; the pure variant skips DB-bound checks for tests).
    - Branch / switch nodes have at least one outbound edge with a non-null label.
    - Wait-for-event nodes have a numeric `max_wait_seconds` ≤ 30 days (otherwise the run would park forever).
    - Action types referenced in nodes exist in the action registry (`resolve(action_type)` succeeds — gate against typos).

- `core/workflows/exceptions.py`:
  - `WorkflowError` (base) → `WorkflowNotFound`, `WorkflowLocked` (edit-while-active-marketing), `InvalidGraph`, `DuplicateWorkflowName`, `FolderHasWorkflows`, `ActivationBlocked` (graph valid but compliance pre-flight fails — Step 12 adds the actual blockers; Step 2 raises with reason "compliance check not implemented yet" — placeholder removed when Step 12 lands).

Out of scope:

- Router (Step 3).
- Engine + step processor (Step 4).
- Trigger subscription (Step 5).
- Condition evaluator (Step 6) — but the validator DOES check that condition nodes carry a `conditions` JSONB object (whose AST shape Step 6 defines).
- Action handlers (Steps 7-11).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/workflows/data_access.py` | edit — extend with list/get/folder helpers |
| `API/src/app/core/workflows/service.py` | **NEW** |
| `API/src/app/core/workflows/graph.py` | **NEW** — validator |
| `API/src/app/core/workflows/exceptions.py` | **NEW** |
| `API/tests/workflows/test_service.py` | **NEW** |
| `API/tests/workflows/test_graph_validator.py` | **NEW** |

**~6 files. ~550 lines.**

## Plan

1. Exceptions module first — every other file imports from it.
2. Graph validator with pure-Python checks; second variant `validate_graph_with_db` for service-layer checks against `tbl_message_templates`.
3. DAL extensions following the existing single-file pattern.
4. Service: create + get + list + update + change_status + archive + folder CRUD.
5. Tests covering the graph-validator branches + service happy-paths + 409 on duplicate name + lock on active-marketing edit.

## DB changes / migrations

None — uses tables from Step 1.

## Tests

14 pytest cases (~half in `test_graph_validator.py`, half in `test_service.py`):

- Graph validator:
  - Valid trigger+send graph passes.
  - Missing trigger → `InvalidGraph`.
  - Two triggers → `InvalidGraph`.
  - Edge with unknown source node id → `InvalidGraph`.
  - Cycle → `InvalidGraph`.
  - Orphan node → `InvalidGraph`.
  - Branch node with no labeled outbound edges → `InvalidGraph`.
  - Wait-for-event with `max_wait_seconds > 30 days` → `InvalidGraph`.
- Service:
  - `create_workflow` persists + writes a v1 version row.
  - Duplicate name in same org → `DuplicateWorkflowName`.
  - Same name in different org allowed (RLS-scoped uniqueness).
  - `update_workflow` bumps `current_version` + writes a new version row.
  - `update_workflow` on an active marketing workflow → `WorkflowLocked`.
  - `change_status('active')` with an invalid graph → `InvalidGraph` re-raised.

## Smoke

```
1. Python shell with RequestContext set:
   svc.create_workflow(payload=WorkflowCreate(name='Welcome', graph={trigger node + send node})) → returns Workflow.
2. svc.update_workflow(...) with a second send node added → current_version=2.
3. svc.change_status(new_status='active') → success.
4. svc.update_workflow(...) → WorkflowLocked (because is_marketing=true + status=active).
5. svc.change_status('paused') → svc.update_workflow(...) → succeeds; next svc.change_status('active') → succeeds.
```

## Risks

- The graph validator's "no cycles" check needs to be tight; v1 only allows the back-edge from wait-for-event timeout. A future "loop until goal" pattern would need a new node type and validator rule — keep this clean.
- Validating template references against the DB on every save could be slow for large workflows. Mitigation: pull the set of `template_id`s used by the graph in one query (`WHERE id IN (...)`), not per-node.

## Self-check (10 rules)

`core/workflows/`. ✓ org_id-scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. N/A permissions (Step 3). pack.yaml untouched. ✓ 6 files / ~550 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 2 — Workflow service + graph validator
Files: 6
Verify: CRUD service operational; graph validator rejects 8 categories of malformed input; active-marketing edit-lock honored.
Tests: 14 pytest cases.
Awaiting "proceed".
```
