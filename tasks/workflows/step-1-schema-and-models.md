# Step 1 — Workflow schema + models + node graph tables

**Goal:** Land the foundation — five new tables (`tbl_workflows`, `tbl_workflow_versions`, `tbl_workflow_runs`, `tbl_workflow_step_runs`, `tbl_workflow_folders`) with RLS, SQLAlchemy models, and Pydantic schemas. No execution yet; no triggers yet; no UI yet.
**Status:** COMPLETED — Five tables shipped via migration `0136_workflows_schema.py`: `tbl_workflow_folders` (parent_folder_id self-FK + unique `(org_id, lower(name), COALESCE(parent, sentinel))` so two "Welcome" folders can coexist at root and inside "Marketing"); `tbl_workflows` (graph JSONB + denormalised `enabled_event_types text[]` with GIN index for the Step-5 matcher + `ab_sibling_id` self-FK SET NULL + `goal_node_id` + `cost_per_run_cents` + unique `(org_id, lower(name))`); `tbl_workflow_versions` (append-only with `uq_workflow_versions_workflow_version`); `tbl_workflow_runs` (three indexes: `(org_id, workflow_id, started_at DESC)` analytics, partial `(org_id, status, next_step_at) WHERE status='pending'` scheduler sweep, `(workflow_id, contact_id, started_at DESC)` re-enrolment dedupe); `tbl_workflow_step_runs` (unique `(run_id, step_index)` + partial `(org_id, started_at DESC) WHERE status='errored'` for the error view). Five new ENUMs: `workflow_status`, `workflow_run_status`, `workflow_run_outcome`, `workflow_step_run_status`, `workflow_re_enrollment_rule`. RLS policies installed on all five tables with the standard `current_setting('app.current_org_id')` gate. FK ondelete policy: workflow → versions/step_runs CASCADE, workflow → runs RESTRICT (preserves history when archiving), contact → runs SET NULL, ab_sibling SET NULL. NEW `core/workflows/__init__.py` documents the concept map (Workflow / Version / Run / StepRun / Folder). NEW `core/workflows/models.py` — five `TenantScoped` ORM classes mirroring the migration verbatim with all five ENUMs declared `create_type=False`; `Workflow.graph_nodes_by_id` helper returns the in-Python `{node_id → node_dict}` map for Step-4's engine. NEW `core/workflows/schemas.py` — strict Pydantic shapes: `WorkflowGraph` enforces no-duplicate node ids, no-duplicate edge ids, and every edge's `source`/`target` must reference a node in the same payload (the Step-2 service layer adds semantic validation on top: single trigger root, no cycles). `WorkflowCreate`/`Update`/`Read`, `WorkflowRunRead`, `WorkflowStepRunRead`, `WorkflowFolderCreate`/`Read` round out the shape contract. NEW `core/workflows/data_access.py` placeholder with a single `get_workflow` query — Steps 2/4/5 will fill in the rest per the locked single-file DAL convention. NEW `core/workflows/actions/__init__.py` — `register_action(action_type, factory)` + `resolve(action_type)` + `is_registered` + `list_registered` + `unregister_action` + test helper `_clear_registry_for_tests`; `ActionNotRegistered` exception drives the engine's "unknown_action" error path. `src/app/main.py` adds a side-effect import of `core.workflows.models` so the five tables land on `Base.metadata` before Alembic / test fixtures sweep. 17 pytest cases across two files: `test_models_import.py` (TenantScoped inheritance, Base.metadata registration, all enum values, WorkflowCreate round-trip, graph rejects missing node id / type / dangling source / dangling target / duplicate node ids); `test_action_registry.py` (register-then-resolve, unknown action raises, overwrite-on-reregister, is_registered + list_registered reflect state, unregister removes). Pytest run deferred per `feedback_pause_before_pytest.md`. Migration applied via `API\run.cmd upgrade` — head is now `0136_workflows_schema`.
**Depends on:** `tasks/template-library/` shipped (Module A — workflows reference `tbl_message_templates.id` from Send action configs). `tasks/automation-engine/` Step 1 shipped (`core/events/bus.py` exists — Step 5 of this track subscribes to it). `tbl_message_templates` + `tbl_contacts` + `tbl_users` + `tbl_organizations` exist.

---

## Scope

In-scope:

- Migration `<ts>_workflows_schema.py` — five tables + four enums + RLS + indexes.

- `tbl_workflows`:
  - `id`, `org_id`, `name`, `description` text nullable, `category` text (Sales / Marketing / Service / Internal / Custom — free string), `folder_id` FK `tbl_workflow_folders` SET NULL, `status` enum (`draft / active / paused / archived`), `current_version` int default 1, `re_enrollment_rule` enum (`once / daily / never`) default `once`, `is_marketing` bool default true (governs whether compliance gates apply to non-transactional Send actions), `graph` JSONB (`{nodes: [...], edges: [...]}`), `ab_sibling_id` UUID nullable (self-FK; Step 18 wires it), `goal_node_id` text nullable (the node id in the graph that completes the run as `goal_reached`), `cost_per_run_cents` int default 0 (operator-supplied estimate for ROI math), `enabled_event_types` text[] (denormalised list pulled from the graph's trigger nodes — matcher-friendly index target), audit cols. Unique `(org_id, lower(name))`.

- `tbl_workflow_versions`:
  - `id`, `org_id`, `workflow_id` CASCADE, `version` int, `graph` JSONB, `change_note` text nullable, `created_by_user_id` UUID nullable, `created_at`. Unique `(workflow_id, version)`. Step 17 writes one row per published edit.

- `tbl_workflow_runs`:
  - `id`, `org_id`, `workflow_id` RESTRICT, `version` int, `contact_id` UUID nullable (SET NULL on contact delete), `trigger_event_id` text nullable (the `event.id` from the bus envelope — Step 5 uses for idempotency / re-enrollment dedupe), `trigger_payload` JSONB, `status` enum (`pending / running / completed / paused / canceled / errored`), `current_node_id` text nullable (the node the run is parked at; null when terminal), `outcome` enum (`goal_reached / completed / canceled / errored`) nullable, `state` JSONB (per-run accumulator — variables emitted by record-update actions live here for downstream nodes to read), `error` text nullable, `started_at`, `next_step_at` (Celery beat sweep target), `completed_at`. Indexes: `(org_id, workflow_id, started_at DESC)` for analytics; partial `(org_id, status, next_step_at) WHERE status='pending'` for the scheduler sweep; `(workflow_id, contact_id, started_at DESC)` for re-enrollment dedupe.

- `tbl_workflow_step_runs`:
  - `id`, `org_id`, `run_id` CASCADE, `node_id` text (the node in the workflow's graph this row tracks), `step_index` int (monotonic per-run for ordering), `status` enum (`pending / running / completed / skipped / errored`), `started_at`, `completed_at` nullable, `output_edge_label` text nullable (which outbound edge the branch / switch took), `skip_reason` text nullable (compliance / condition_failed / opt_out / quiet_hours / frequency_cap), `payload` JSONB (the resolved action config — useful for diagnostics so the operator sees the exact values the engine evaluated), `error` text nullable. Indexes: `(run_id, step_index)` unique; `(org_id, started_at DESC) WHERE status='errored'` for the run-history error view.

- `tbl_workflow_folders`:
  - `id`, `org_id`, `name`, `parent_folder_id` self-FK nullable, `display_order` int. Unique `(org_id, lower(name), parent_folder_id)`. Step 13's list UI hangs workflows off these.

- SQLAlchemy models in `core/workflows/models.py` — `Workflow`, `WorkflowVersion`, `WorkflowRun`, `WorkflowStepRun`, `WorkflowFolder`, all `TenantScoped`. Status / outcome / skip_reason / re_enrollment / node-type enums declared with `create_type=False` since the migration creates them.

- Pydantic schemas in `core/workflows/schemas.py`: `WorkflowCreate / WorkflowUpdate / WorkflowRead / WorkflowGraph (nodes[] + edges[])`, `WorkflowRunRead`, `WorkflowStepRunRead`, `WorkflowFolderCreate / Read`.

- `core/workflows/__init__.py` + `core/workflows/data_access.py` (single-file placeholder per the locked layered convention; Steps 2 / 4 / 5 fill in query bodies).

- `core/workflows/actions/__init__.py` — the action-registry stub (`register_action(action_type: str, handler)` + `resolve(action_type: str)`); no actions registered yet.

Out of scope:

- Service / router / engine / triggers / actions / compliance / UI / seeds — all separate steps.
- Cycle detection beyond a trivial JSON schema check — full DAG validation is Step 2.
- Migration data backfill — there's no prior data to backfill.

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_workflows_schema.py` | **NEW** |
| `API/src/app/core/workflows/__init__.py` | **NEW** — docstring |
| `API/src/app/core/workflows/models.py` | **NEW** — five models + enums |
| `API/src/app/core/workflows/schemas.py` | **NEW** — Pydantic shapes |
| `API/src/app/core/workflows/data_access.py` | **NEW** — empty placeholder |
| `API/src/app/core/workflows/actions/__init__.py` | **NEW** — `register_action` / `resolve` |
| `API/tests/workflows/__init__.py` | **NEW** — empty |
| `API/tests/workflows/test_models_import.py` | **NEW** |
| `API/tests/workflows/test_action_registry.py` | **NEW** |

**~9 files. ~600 lines.** Slightly over the spec-MD-typical ~400 lines because five tables + the action registry stub all land together; splitting would force premature commits before the action registry can be filled.

## Plan

1. Migration first — enums (workflow_status, run_status, run_outcome, step_run_status, re_enrollment_rule, skip_reason), five tables with FKs (workflow → versions/runs CASCADE, contact SET NULL, message_template RESTRICT), RLS + tenant policies, indexes per the in-scope spec.
2. Models matching verbatim. `Workflow.graph` typed as `JSONB`; helper property `graph_nodes_by_id` (in-Python dict access, not a separate column).
3. Pydantic schemas with strict typing for the `WorkflowGraph` shape (node has `id` / `type` / `position` / `config`; edge has `id` / `source` / `target` / `label`).
4. Action registry stub — same pattern as `core/conversations/registry.py`: module-level `_factories` dict, `register_action(name, factory)` + `resolve(name)`. Empty at Step 1; Steps 7-11 populate.
5. Tests: model importability + TenantScoped inheritance + Base.metadata registration + Pydantic round-trip + action registry register-then-resolve + unknown-action raises `ActionNotRegistered`.

## DB changes / migrations

Five new tables + six new enums. Reversible (downgrade drops tables in FK-safe order + drops the enums).

## Tests

8 pytest cases:

- All five models import + inherit `TenantScoped`.
- Status / outcome / re_enrollment / skip_reason enums carry the documented values.
- All five tables registered with `Base.metadata`.
- `WorkflowCreate` Pydantic round-trips with `graph={nodes: [], edges: []}`.
- `WorkflowGraph` rejects nodes without `id`/`type`.
- `WorkflowGraph` rejects edges referencing missing node ids.
- Action registry: `register_action + resolve` returns the same factory.
- Unknown action: `resolve("nope")` raises `ActionNotRegistered`.

## Smoke

```
1. run.cmd upgrade — migration applies.
2. \dt tbl_workflow* — five tables visible.
3. INSERT a workflow row + a folder row via SQL with explicit org_id; SELECT confirms back.
4. Python: from src.app.core.workflows.actions import register_action, resolve;
   register_action("send.email", lambda: object()); resolve("send.email") → factory().
```

## Risks

- JSONB `graph` column is flexible but loosely-typed; Step 2's validator MUST reject malformed graphs at the service layer (the DB allows anything JSON-shaped).
- Five tables in one migration — large reversible block. Each statement is short; total transaction is well under any practical lock-hold timeout.
- `ab_sibling_id` self-FK is nullable + uses ON DELETE SET NULL so an archived workflow doesn't cascade-delete its sibling.

## Self-check (10 rules)

`core/workflows/` only. ✓ org_id + RLS on all five tables. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar (Step 3). N/A permissions (Step 3). pack.yaml untouched. ✓ 9 files / ~600 lines — slightly over but justified (five-table foundation). Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 1 — Workflow schema + models + node graph tables
Files: 9
Verify: five tables visible; models importable + TenantScoped; action registry register-then-resolve.
Tests: 8 pytest cases.
Awaiting "proceed".
```
