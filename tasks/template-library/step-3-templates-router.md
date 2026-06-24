# Step 3 — Templates router and permissions

**Goal:** REST endpoints for CRUD + version history + preview. Register five new permission keys and mount the router under `/api/v1/templates`.
**Status:** Pending
**Depends on:** Step 1 (schema), Step 2 (service).

---

## Scope

In-scope:
- `core/templates/router.py` — endpoints:
  - `GET /api/v1/templates` — list (query: `channel`, `internal_status`, `external_status`, `q`, `limit`, `offset`). Gated on `templates.read`.
  - `POST /api/v1/templates` — create. Gated on `templates.write`.
  - `GET /api/v1/templates/{id}` — read with current-version body. Gated on `templates.read`.
  - `PATCH /api/v1/templates/{id}` — edit draft (creates new version row). Gated on `templates.write`.
  - `DELETE /api/v1/templates/{id}` — soft archive. Gated on `templates.write`.
  - `GET /api/v1/templates/{id}/versions` — version list. Gated on `templates.read`.
  - `GET /api/v1/templates/{id}/versions/{v}` — specific past version. Gated on `templates.read`.
  - `POST /api/v1/templates/{id}/preview` — render with sample context. Gated on `templates.read`.
  - `GET /api/v1/templates/variables/{channel}` — discovery endpoint returning allowed `{{tags}}` per channel from the Step-2 registry. Gated on `templates.read`.
- Five new permission keys registered: `templates.read`, `templates.write`, `templates.review`, `templates.publish`, `templates.submit_external` (declared here; only `read`/`write` used in this step — `review`/`publish` come online in Step 4, `submit_external` in Step 9 + 12).
- `core/templates/permissions.py` — permission key constants + registration with the core RBAC composer.
- Owner + Admin role templates gain all five keys; Employee gets `read` only — added to the role-template seed used at org creation (mirrors how `whatsapp.templates.*` got seeded in `whatsapp-platform-upgrade` Step 8).
- Backfill migration `<ts>_bf_templates_perm.py` adds the five keys to existing Owner/Admin role rows (mirrors `0095`/`0101`/`0105` pattern).
- Mount the new router from `main.py`.
- API tests covering each endpoint (200 + 401 + 403 + 404 + tenant-isolation cases).

Out of scope:
- Module descriptor / sidebar registration (Step 5).
- Workflow state-transition endpoints (Step 4).
- Test-send endpoint (Step 5).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/templates/router.py` | **NEW** |
| `API/src/app/core/templates/permissions.py` | **NEW** |
| `API/alembic/versions/<ts>_bf_templates_perm.py` | **NEW** — backfill perm keys onto Owner/Admin role rows |
| `API/src/app/main.py` | edit — `include_router(templates_router)` |
| `API/src/app/core/auth/role_templates.py` | edit — add five keys to Owner/Admin template; Employee gets read only |
| `API/tests/templates/test_router.py` | **NEW** |

**~6 files. ~400 lines.**

## Plan

1. `permissions.py` — define key constants. Register with the same RBAC registry that `whatsapp.templates.*` uses.
2. `router.py` — endpoints calling Step-2 service. Use `RequestContext` to resolve `org_id` from JWT.
3. Pydantic request/response shapes already exist from Step 1; the router glues them.
4. Migration backfills role rows for existing tenants.
5. `role_templates.py` — extend the seeded Owner/Admin/Employee shapes so new orgs created after this step get the keys.
6. Mount router in `main.py`.
7. Tests cover: list pagination, filter combinations, RLS isolation across orgs, 403 for missing perm, 404 for stale id, 422 for invalid payload.

## DB changes / migrations

One backfill migration — no schema change. Reversible (downgrade removes the five keys from existing role rows).

## Tests

8-10 pytest cases:
- `test_list_returns_only_my_org_templates`
- `test_create_requires_write_perm`
- `test_read_with_only_write_perm_works` (write implies read in this RBAC)
- `test_update_increments_version`
- `test_update_locked_template_returns_409`
- `test_archive_marks_internal_status_archived`
- `test_versions_list_returns_descending_by_version`
- `test_preview_resolves_variables`
- `test_preview_unknown_variable_yields_empty`
- `test_variables_endpoint_returns_channel_registry`

## Smoke

```
1. POST /api/v1/templates {name, channel=email, body_text, subject} → 200, returns id + version=1.
2. PATCH that id with new body → 200, current_version=2.
3. GET /api/v1/templates/{id}/versions → returns 2 rows.
4. POST /api/v1/templates/{id}/preview {context: {...}} → 200, rendered subject + body.
5. GET /api/v1/templates/variables/email → returns the variable list.
6. As a different org's Owner, GET /api/v1/templates/{id} → 404 (RLS).
7. As Employee (read only), POST /api/v1/templates → 403.
```

## Risks

- Permission backfill must be idempotent (skip rows where the key is already present). Mirror the `0095_bf_*` pattern.
- The discovery endpoint (`/variables/{channel}`) is hit on every editor open; cache the registry in memory (it's static per process lifecycle).

## Self-check (10 rules)

`core/templates/`. ✓ org_id on every endpoint. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar (Step 5). Permissions registered via registry. ✓ pack.yaml untouched. ✓ 6 files / ~400 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 3 — Templates router and permissions
Files: 6
Verify: nine REST endpoints live + five perm keys registered + backfilled on existing Owner/Admin.
Tests: 10 pytest cases.
Awaiting "proceed".
```
