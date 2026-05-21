# Step 1 — Backend: org-wide list endpoint + filter params

**Goal:** Enable an Owner / Admin / anyone with `users.read` to fetch all tasks in their org, with status + priority + assignee + search filters. Keeps the existing entity-scoped `GET /tasks` and personal `GET /tasks/me` paths unchanged.
**Track:** Tasks page
**Status:** Pending
**Depends on:** Phase 2 tasks module (CRUD + schemas already in place).

---

## Scope

The existing `GET /api/v1/tasks` requires `related_entity_type` + `related_entity_id` (entity-scoped only). The frontend Tasks page (Step 2) needs an org-wide view; that endpoint shape doesn't exist yet. Three small backend changes:

1. **New endpoint** `GET /api/v1/tasks/all` — list every task in the caller's org, gated on `users.read`. Supports the filters the list page needs.
2. **Extend** `GET /api/v1/tasks/me` — accept the same filter params so the personal view is consistent.
3. **No change** to existing `GET /api/v1/tasks?related_entity_type=…&related_entity_id=…` (entity panel keeps working).

Picking a separate `/tasks/all` route rather than relaxing the existing `/tasks` keeps the permission gate explicit (the entity-scoped endpoint requires only `tasks.read`; the new all-org endpoint requires the stricter `users.read`) and avoids breaking any existing callers.

## Filter parameters (shared between `/me` and `/all`)

| Param | Type | Notes |
|---|---|---|
| `status` | `open` \| `done` \| `cancelled` | Optional. |
| `priority` | `low` \| `med` \| `high` | Optional. |
| `assigned_to_id` | UUID | Optional. `/all` only — `/me` ignores it (always = caller). |
| `q` | string | Optional. Case-insensitive `ILIKE %q%` on `tasks.title`. |
| `due_filter` | `today` \| `overdue` \| `upcoming` | Optional. Server-side date math against `now()`. |
| `sort_by` | `due_at` \| `priority` \| `title` \| `created_at` | Default: `due_at` ascending; nulls last. |
| `sort_dir` | `asc` \| `desc` | Default: `asc`. |
| `page` | int | Default 1. |
| `size` | int | Default 50, max 200. |

## Endpoint behavior

| Endpoint | Auth | Behavior |
|---|---|---|
| `GET /api/v1/tasks/all` | `require_permissions("users.read")` | Returns every active task in the caller's org, filtered as above. 403 for callers without `users.read`. Returns the existing `TaskListResponse` shape. |
| `GET /api/v1/tasks/me` (extend) | `require_permissions("tasks.read")` | Existing behavior unchanged for callers passing only `status`; new optional `priority` / `q` / `due_filter` / `sort_by` / `sort_dir` params accepted and applied. |

The existing entity-scoped `GET /api/v1/tasks` is left alone.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/tasks/router.py` | modified — add `GET /all` endpoint; extend `/me` signature with new optional params |
| `api/src/app/core/tasks/service.py` | modified — new `list_all_in_org(...)` query helper; extend `list_my_tasks(...)` to accept the shared filter shape; refactor common WHERE-clause + sort-by builder into a tiny `_apply_task_filters(stmt, ...)` helper |
| `api/src/app/core/tasks/schemas.py` | modified (small) — add `TaskListFilter` Pydantic model that the new endpoint can use for its query params if it makes the router signature cleaner |

**3 files modified. No migrations. No new permission keys.**

## Plan

1. In `service.py`:
   - Add a private `_apply_task_filters(stmt, *, status, priority, q, due_filter, sort_by, sort_dir)` that takes a base `select(Task)` and adds the requested WHERE/ORDER clauses. Single source of truth.
   - Add `list_all_in_org(db, *, org_id, filters, page, size) -> (rows, total)` that starts from `select(Task).where(Task.org_id == org_id)` and runs through the filter helper.
   - Extend `list_my_tasks(...)` signature to accept the same filter args (optional). Keep existing callers compatible (defaults).
2. In `router.py`:
   - Add `GET /all` endpoint, `require_permissions("users.read")`, accepts the filter query params, returns `TaskListResponse`.
   - Update `GET /me` to accept the new params and pass them through. Permission stays `tasks.read`.
3. In `schemas.py`: if the router signature gets noisy, introduce `TaskListFilter` Pydantic v2 model and use `Depends()` to assemble it. Otherwise keep query params inline — judgment call at implementation time.
4. Smoke-test all four cases below.

## Smoke

```
# 1) Owner sees all tasks in core-demo (should succeed):
curl -s -H "Authorization: Bearer $OWNER" "http://localhost:8000/api/v1/tasks/all" | jq '.total'

# 2) Employee gets 403 on /all (lacks users.read):
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $EMPLOYEE" "http://localhost:8000/api/v1/tasks/all"
# Expected: 403

# 3) /me still works for Employee:
curl -s -H "Authorization: Bearer $EMPLOYEE" "http://localhost:8000/api/v1/tasks/me" | jq '.total'

# 4) Filters compose:
curl -s -H "Authorization: Bearer $OWNER" "http://localhost:8000/api/v1/tasks/all?status=open&priority=high&due_filter=overdue&sort_by=due_at&sort_dir=asc" | jq '.items | length'

# 5) Search:
curl -s -H "Authorization: Bearer $OWNER" "http://localhost:8000/api/v1/tasks/all?q=follow" | jq '.items[].title'

# 6) New params on /me also work:
curl -s -H "Authorization: Bearer $EMPLOYEE" "http://localhost:8000/api/v1/tasks/me?due_filter=overdue&priority=high" | jq '.total'
```

## Risks

- **due_filter math at the DB layer** — `today` / `overdue` / `upcoming` need server-side comparisons against `now()` in UTC. Use `func.date(Task.due_at) = func.current_date()` for `today`, `Task.due_at < func.now()` for `overdue`, `Task.due_at > func.now()` for `upcoming`. Tasks with `due_at IS NULL` are excluded from these filters (which is correct — undated tasks aren't overdue).
- **Sort with nullable `due_at`** — Postgres puts NULLs first by default on `ASC`. We want them last (an undated task shouldn't pre-empt the most-overdue ones). Use `Task.due_at.asc().nullslast()` / `.desc().nullsfirst()` accordingly.
- **Cross-tenant safety** — `list_all_in_org` MUST always include the `Task.org_id == org_id` filter; tests should pin this against the demo org by attempting a cross-org read (should return 0 rows).
- **Test coverage** — pytest deferred (per project policy); the smoke above is the gate.

## Rollback

Revert the 3 modified files. The `/me` endpoint reverts to the smaller filter shape; the new `/all` endpoint disappears. Frontend Tasks page (Step 2) breaks if shipped after rollback — ship/rollback together.
