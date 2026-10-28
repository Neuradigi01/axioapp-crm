# Tasks page

A focused track for the standalone `/user/tasks` page — the standard CRM "all my tasks / all team tasks" view that today's sidebar entry points to but doesn't actually load. Sits outside the numbered phase tree — vertical-neutral, ship-when-ready.

## Why this exists

The Tasks module declares a sidebar entry at `frontend_route="/user/tasks"`, but no Angular route matches it. Clicking the entry falls through the `**` wildcard in [app.routes.ts](../../APP/src/app/app.routes.ts) and bounces to the login page — a broken user-facing experience. The backend has a full tasks CRUD (`GET /api/v1/tasks/me`, `GET /api/v1/tasks`, `POST/PATCH/DELETE /tasks/{id}`) and two task UIs exist (the entity-scoped panel embedded on contact/lead pages, and the header "My tasks" popover), but nothing aggregates tasks in a dedicated full-page view.

Three gaps this track closes:

| Gap | What's missing today |
|---|---|
| **No standalone Tasks list page** | The sidebar promises `/user/tasks`; clicking it 404s through the wildcard and dumps the user on `/accounts/login`. |
| **No "all org tasks" view for managers** | The existing `GET /tasks` requires `related_entity_type` + `related_entity_id` query params (entity-scoped only). An Owner/Admin who wants to see *every* task in the org has no endpoint to call. |
| **No quick-complete / quick-create from a global view** | The header popover lists tasks but offers no create. The entity panel allows create but only inside one contact/lead. Standard CRM expectation is a one-click create + checkbox-to-complete on the dedicated page. |

## Standard CRM Tasks page — what we'll match

| Feature | Pattern |
|---|---|
| **Permission-scoped view** | Owner/Admin/anyone with `users.read` → all-org tasks. Otherwise → personal scope only. Same Pattern 1 we used for Dashboard. |
| **Filter chips** | `All` (org scope only) · `Mine` · `Due today` · `Overdue` · `Done` |
| **Sortable columns** | Title, status, priority, due date, assignee. Default sort: due_at ascending (oldest-overdue first). |
| **Quick complete** | Checkbox in the leftmost column flips status `open ↔ done` in place (PATCH /tasks/{id}). |
| **Create button** | Opens a modal with: title (required), description, due date, priority (low/med/high), assignee (defaults to caller), related entity (optional). |
| **Click row** | Opens the same modal in edit mode. |
| **Empty / loading states** | Skeleton list while loading; "No tasks yet" with a Create CTA when empty. |
| **Header KPIs** | Small inline counters: `<N> open` · `<M> overdue` · `<K> due today`. |

Anything beyond this (board view, recurring tasks, subtasks, bulk operations) is out of scope for v1 — explicit follow-ups.

## What this does NOT do

- Does not add new permission keys. Reuses `tasks.read` / `tasks.write`.
- Does not introduce recurring tasks, subtasks, or templates (each is its own follow-up).
- Does not add a kanban board view (v2 polish).
- Does not change the entity-scoped panel or the header popover — both keep working unchanged. The new page is additive.
- Does not deal with notifications/reminders (separate track once the notifications module is fleshed out).
- Does not change `menu_position=300` for the Tasks module in the sidebar.

## Acceptance criteria

A user logs in → clicks **Tasks** in the sidebar → they:

1. **Land on `/user/tasks`** (no more bounce to login).
2. **See the right scope automatically:**
   - Owner / Admin / Sales Manager (template) → view defaults to `All` showing every active task in the org.
   - Employee / Support Agent → view restricted to `Mine`; the `All` chip is hidden.
3. **See header KPIs** with live counts.
4. **Filter by chip** — clicks switch between `All` / `Mine` / `Due today` / `Overdue` / `Done` without a full reload.
5. **Sort** by clicking a column header — title, due date, priority.
6. **Search** by title (debounced 250 ms).
7. **Mark complete** — checkbox in leftmost column; row strikes through and moves under the active filter rules (e.g. disappears from `Overdue`).
8. **Click any row** — opens an edit modal.
9. **Click "Create task"** — opens a modal, submits, new row appears.
10. **Permission failures fail loudly** — an Employee hitting `/api/v1/tasks/all` directly gets 403 (the endpoint enforces `users.read`).

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Backend: org-wide list endpoint + filter params](step-1-backend-org-list-endpoint.md) | Pending | ~½ day |
| 2 | [Frontend: tasks list page + create/edit modal](step-2-frontend-tasks-list-page.md) | Pending | ~1 day |

**Total: ~1.5 working days.** Stop and report after each per Rule 9.

## Dependencies

- Phase 2 tasks module (data, CRUD, schemas) — Done.
- RBAC Step 4 (permission guards, `users.read` gate) — Done; the new endpoint reuses `require_permissions("users.read")` for the all-org path.
- The Tasks module descriptor — already registered (`menu_position=300`, sidebar entry already shows).

## File budget

| Area | Files | Notes |
|---|---|---|
| Backend (Step 1) | 1 modified (`router.py`), 1 modified (`service.py`) for the new `list_all_tasks_in_org` query + filter handling; 1 modified (`schemas.py`) if a TaskFilter request model helps. No migrations. | |
| Frontend (Step 2) | 3 new (`tasks.page.ts/html`, `task-form-modal.component.ts/html`), 1 modified (`tasks-api.service.ts` to add `listAll(...)` + filter args), 1 modified (`user.routes.ts` to add `/tasks` route) | Tailwind only; no Material. |
| Tests | Curl/PowerShell smoke is the gate; no pytest in v1. | |

**Total ~7 files. No migrations. No new permission keys.**

## Invariants this track enforces

| Rule | Where |
|---|---|
| All-org list requires `users.read` | New endpoint gates on it explicitly |
| Personal-only paths require only `tasks.read` | Existing `/tasks/me` semantics preserved |
| Task creation always carries `assigned_to_id` | Backend rejects missing assignee (existing behavior) |
| Marking complete preserves `done_at` semantics | PATCH endpoint already sets timestamps; we don't bypass it |
| Frontend never assumes a card key beyond what backend declares | Same generic-renderer discipline as Dashboard — sort columns / filter chips are declared, not hardcoded per-task-type |

## Self-check against the 10 rules

- ✅ Rule 1: `core/tasks/` never touches packs.
- ✅ Rule 2: No new DB tables.
- ✅ Rule 3: `custom_data` JSONB on `tasks` already exists; this track doesn't change the schema.
- ✅ Rule 4: Form fields rendered statically — Task is a core entity, not custom-field-bearing.
- ✅ Rule 5: Sidebar entry already registered; this track just makes the destination real.
- ✅ Rule 6: Permission registry unchanged. `users.read` reused for the org-scope gate.
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: 7 files across 2 steps; each step < 30 min review.
- ✅ Rule 9: Stop-and-report after each step.
- ✅ Rule 10: No TODOs. v1 ships complete.

## After this track

- Clicking Tasks in the sidebar finally goes somewhere real.
- Managers have an org-wide task view; ICs have a personal task view; same page.
- Foundation for v2 follow-ups: board view, recurring tasks, bulk operations.
