# Step 2.8 — Tasks: backend + frontend

**Goal:** `tasks` table, CRUD, "my tasks" endpoint with due-date logic. UI: Tasks panel on contact detail + global "My Tasks" view in header dropdown.
**Phase:** 2
**Depends on:** 2.5
**Status:** Pending

## Scope
**In-scope:**
- Model `Task` (TenantScoped): id, org_id, title, description, due_at, assigned_to_id (FK→users), related_entity_type, related_entity_id, status (open/done/cancelled), priority (low/med/high), created_at, updated_at.
- Migration + RLS + indexes (`assigned_to_id`, `due_at`, `(related_entity_type,related_entity_id)`).
- Service + endpoints: CRUD, `GET /tasks/me?status=open` returning current user's tasks ordered by due date.
- Permissions: `tasks.read`, `tasks.write`.
- Frontend:
  - `tasks-api.service.ts`
  - `tasks-panel.component.ts/.html` for contact detail (`(entityType, entityId)`).
  - `my-tasks-popover.component.ts/.html` opened from header.
  - Add a "Tasks" tab to contact detail.

**Out of scope:**
- Reminders / notifications wired up — 2.15+.

## Files to touch
- `api/app/core/tasks/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0009_tasks.py` (created)
- `app/src/app/features/user/core/tasks/*` (created)
- `app/src/app/features/user/core/contacts/contact-detail.page.html` (modified)
- `app/src/app/features/user/core/layout/header.component.html` (modified — popover trigger)

## Plan
1. Backend model + migration.
2. CRUD endpoints. `GET /tasks/me` joins via current user from JWT.
3. Frontend tasks-panel: list + checkbox to mark done + add-task inline form.
4. My-tasks popover: triggered by header bell-adjacent icon (or extend header to add a tasks icon). Lists tasks grouped by Overdue / Today / Later.

## Tests to add
- `tests/test_tasks_crud.py`
- `tests/test_tasks_my.py` — assigned_to scoping + ordering.

## Verification checklist
**Backend/Frontend:**
- create a task on a contact via Tasks tab → appears.
- mark done → strikethrough; status persists.
- header tasks popover → shows the task with due-date grouping.

## Self-check (10 rules)
- [ ] org_id + RLS.
- [ ] Step ≤ ~12 files (allow up to 12 here since it's backend+frontend combined; split if larger).

## Stop & report
Await "proceed" before Step 2.9.
