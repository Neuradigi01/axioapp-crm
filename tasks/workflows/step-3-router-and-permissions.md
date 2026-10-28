# Step 3 — Workflow router + permissions registry

**Goal:** REST endpoints under `/api/v1/workflows` + `core/workflows/module.py` registering the sidebar entry + six permission keys.
**Status:** COMPLETED — NEW `core/workflows/permissions.py` declares six `PERM_*` constants + `ALL_KEYS` + `OWNER_KEYS` / `ADMIN_KEYS` / `EMPLOYEE_KEYS` fanout lists imported by name from the role-template seeder + backfill migration (no string duplication). NEW `core/workflows/module.py` registers the sidebar entry with `id='workflows'`, name "Workflows", icon `git-branch`, `route='/api/v1/workflows'`, `frontend_route='/user/workflows'`, `menu_position=270` (spec said 260 but that clashed with the already-shipped Automations module; 270 keeps the logical Templates 250 → Automations 260 → Workflows 270 → Campaigns 300 grouping). NEW `core/workflows/router.py` mounts 12 endpoints with the standard `_workflow_http_map` exception translator (404 for NotFound, 409 for Duplicate / Locked / FolderHasWorkflows / ActivationBlocked, 422 for InvalidGraph — InvalidGraph + ActivationBlocked + FolderHasWorkflows include structured `{code, reason/count}` detail so the editor can surface specific failure modes): `GET /workflows` (paginated list, filterable by status/category/folder_id/q + limit/offset, `workflows.read`); `POST /workflows` (`workflows.write`); `GET /workflows/{id}` (`workflows.read`); `PATCH /workflows/{id}` (`workflows.write`); `DELETE /workflows/{id}` (soft archive 204, `workflows.write`); `POST /workflows/{id}/activate` (`workflows.activate`); `POST /workflows/{id}/pause` (`workflows.activate`); `POST /workflows/{id}/archive` (`workflows.write`); `POST /workflows/{id}/clone {name}` (returns fresh draft with `current_version=1`, copies graph + scalar fields, `workflows.clone`); `GET/POST /workflows/folders`; `PATCH/DELETE /workflows/folders/{id}` (`workflows.write`). Folder routes mounted FIRST (before `/{workflow_id}`) so `/workflows/folders` doesn't get swallowed by the UUID path. `ValueError` from invalid state transitions maps to 409. `core/permissions/role_templates.py` extended: `_CORE_ADMIN_KEYS` includes all six workflows keys (Owner inherits via `_CORE_OWNER_KEYS = _CORE_ADMIN_KEYS + [...]`); `_CORE_EMPLOYEE_KEYS` gets `workflows.read` + `workflows.view_analytics` so the sidebar entry + analytics surface read-only for junior staff. Backfill migration `0137_bf_workflows_perm.py` registers the six keys via `ON CONFLICT DO NOTHING` (self-sufficient against the lifespan sweep), fans Owner+Admin grants for all six keys + Employee grants for `read + view_analytics` via `INSERT … ON CONFLICT DO NOTHING` JOIN, fully reversible. `src/app/main.py` adds the workflows router include AND a side-effect `import src.app.core.workflows.module` so the MODULE descriptor lands on the registry before the lifespan permission-fanout sweep runs. 9 pytest cases in `test_router.py`: POST 201 + happy graph; POST 422 with `InvalidGraph` reason; POST 403 without `workflows.write`; GET list filters by status (draft visible, active empty); POST /activate 200 + status flips; POST /clone 201 with fresh draft; DELETE /folders/{id} 409 with `{code:'folder_has_workflows', count:1}`. 5 pytest cases in `test_permissions_registration.py`: module descriptor shape, registry registration, role-template fanout, OWNER_KEYS == ADMIN_KEYS == ALL_KEYS, six keys land in `tbl_permissions`. Migration applied via `API\run.cmd upgrade` — head is now `0137_bf_workflows_perm`. Pytest run deferred per `feedback_pause_before_pytest.md`.
**Depends on:** Step 2 (service exposes the CRUD surface).

---

## Scope

In-scope:

- Permission keys (registered via `core/workflows/module.py` → `module_registry`):
  - `workflows.read` — list / get / view analytics summary.
  - `workflows.write` — create / patch / archive / folder CRUD.
  - `workflows.activate` — change status `draft → active`, `paused ↔ active`, archive (separate so a junior author can draft without going live).
  - `workflows.clone` — clone-from-template + clone-existing.
  - `workflows.view_analytics` — Step 19 analytics dashboards.
  - `workflows.view_diagnostics` — Step 19 "why didn't this fire?" tool (sensitive — exposes contact data + rule logic).

  Default fanout per the project's role-template convention:
  - Owner: all six.
  - Admin: `read / write / activate / clone / view_analytics / view_diagnostics`.
  - Employee: `read / view_analytics` only.

  Backfill migration `<ts>_bf_workflows_perm.py` registers the keys + grants to existing Owner / Admin / Employee roles across every org (same fanout pattern as `0118_bf_templates_perm`).

- `core/workflows/router.py` mounted at `/api/v1/workflows`:
  - `GET /workflows` — list with filters `category`, `folder_id`, `status`, `q`, `limit`, `offset`. `workflows.read`.
  - `POST /workflows` — create from `WorkflowCreate`. `workflows.write`.
  - `GET /workflows/{id}` — read. `workflows.read`.
  - `PATCH /workflows/{id}` — update. `workflows.write`.
  - `DELETE /workflows/{id}` — soft-archive (same as `change_status('archived')`). `workflows.write`.
  - `POST /workflows/{id}/activate` — body `{}` (no payload). `workflows.activate`.
  - `POST /workflows/{id}/pause` — `workflows.activate`.
  - `POST /workflows/{id}/archive` — `workflows.write`.
  - `POST /workflows/{id}/clone` — body `{name: str}`. Returns the new workflow row (draft, fresh `current_version=1`, copies the graph). `workflows.clone`.
  - `GET /workflows/folders` — list folders for the org. `workflows.read`.
  - `POST /workflows/folders` — create folder. `workflows.write`.
  - `PATCH /workflows/folders/{id}` — rename / move. `workflows.write`.
  - `DELETE /workflows/folders/{id}` — refuses when non-empty. `workflows.write`.

  Standard error mapping: `WorkflowNotFound → 404`, `DuplicateWorkflowName → 409`, `InvalidGraph → 422` (with `reason` in detail), `WorkflowLocked → 409`, `FolderHasWorkflows → 409`, `ActivationBlocked → 409`.

- `core/workflows/module.py` — registers the sidebar entry (label "Workflows", icon `git-branch` or `workflow` from Lucide; verify the icon name when wiring the frontend), `menu_position=260` (right after Templates which is 250 from `tasks/template-library/` Step 5). Registers the six permission keys.

- `main.py` — `app.include_router(workflows_router)` after the templates router.

Out of scope:

- Engine + run history endpoints (Step 4 ships `GET /workflows/{id}/runs` + `GET /runs/{id}/steps`).
- Trigger endpoints / events publishing (Step 5).
- Analytics endpoints (Step 19).
- Diagnostics endpoints (Step 19).
- Frontend (Steps 13+).

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_bf_workflows_perm.py` | **NEW** — permission key + role-template backfill |
| `API/src/app/core/workflows/permissions.py` | **NEW** — six PERM_* constants |
| `API/src/app/core/workflows/router.py` | **NEW** |
| `API/src/app/core/workflows/module.py` | **NEW** — sidebar + permission registration |
| `API/src/app/main.py` | edit — include router + side-effect import the module |
| `API/src/app/core/permissions/role_templates.py` | edit — add the six keys to Owner/Admin/Employee templates |
| `API/tests/workflows/test_router.py` | **NEW** |
| `API/tests/workflows/test_permissions_registration.py` | **NEW** |

**~8 files. ~450 lines.**

## Plan

1. Migration: register the six keys in `tbl_permissions`, fan out to existing Owner/Admin/Employee role rows across all orgs (mirror the structure of `0118_bf_templates_perm`).
2. Permission constants + role-template registry edits.
3. Module file (`MODULE` constant — id, label, route, icon, menu_position, permission_keys).
4. Router — endpoints with the standard exception → HTTP mapping helpers (similar to templates router's `_workflow_http_map`).
5. Tests: each endpoint returns the right HTTP code on happy + sad paths; permission denials return 403; sidebar entry surfaces in the registry after import.

## DB changes / migrations

One backfill migration — `INSERT INTO tbl_permissions` + `INSERT INTO tbl_role_permissions` join.

## Tests

10 pytest cases:

- `POST /workflows` 201 with valid payload.
- `POST /workflows` 422 on InvalidGraph (reason in detail).
- `POST /workflows` 403 without `workflows.write` perm.
- `GET /workflows` returns list filtered by status.
- `POST /workflows/{id}/activate` 200 + status flips.
- `POST /workflows/{id}/activate` 422 if graph invalid (forwarded reason).
- `POST /workflows/{id}/clone` returns a new draft.
- `DELETE /workflows/folders/{id}` 409 when folder non-empty.
- Module registration: import `core.workflows.module` → registry knows about "workflows" sidebar entry.
- Permission key registration: post-migration, `tbl_permissions.key` contains all six.

## Smoke

```
1. run.cmd upgrade — backfill applies.
2. Browser → /user/sidebar → "Workflows" entry visible for Owner/Admin/Employee.
3. curl POST /api/v1/workflows with a draft graph → 201.
4. curl POST /api/v1/workflows/{id}/activate → 200; status='active' in DB.
5. Without auth: any endpoint → 401.
6. With Employee token: POST /workflows → 403.
```

## Risks

- Backfill INSERT against `tbl_permissions` must be idempotent (Step 3 may be re-run in dev environments). Use `ON CONFLICT DO NOTHING`.
- Sidebar entry's `menu_position=260` slots between Templates (250) and Settings — confirm no clash with another module the user has installed.

## Self-check (10 rules)

`core/workflows/`. ✓ org_id-scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ Sidebar registered ✓. Permission registry ✓. pack.yaml untouched. ✓ 8 files / ~450 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 3 — Workflow router + permissions
Files: 8
Verify: 12 endpoints live under /api/v1/workflows; 6 permission keys registered + fanned out; sidebar entry surfaces for Owner/Admin/Employee.
Tests: 10 pytest cases.
Awaiting "proceed".
```
