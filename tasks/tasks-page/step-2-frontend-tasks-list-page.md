# Step 2 — Frontend: tasks list page + create/edit modal

**Goal:** Build `/user/tasks` — the standalone CRM tasks page. Permission-scoped (Owner/Admin see all; Employee sees own), with filter chips, sortable columns, quick-complete checkbox, search, and a create/edit modal. Reuses the existing `TasksApiService`.
**Track:** Tasks page
**Status:** COMPLETED — page + modal + route shipped; sidebar Tasks click now lands on a real page. Permission scope branches off `/me`'s `users.read` perm. The "Related entity" picker dropped to a read-only column for v1 (typeahead deferred). The existing `my-tasks-popover` got its `listMine('open')` call migrated to the new `listMine({ status: 'open' })` shape. TypeScript compile + dev build clean. Visual smoke pending human eyeball.
**Depends on:** Step 1 (backend `/tasks/all` endpoint + extended `/tasks/me` filters).

---

## Scope

One new page component + one new modal + a small `TasksApiService` extension + one route entry. No new Angular modules. Tailwind-only styling per the new-page policy.

## Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  Tasks                                                           │
│  3 open · 1 overdue · 2 due today                  [+ Create]    │
├──────────────────────────────────────────────────────────────────┤
│  [ All ] [ Mine ] [ Overdue ] [ Due today ] [ Done ]   🔍 search │
├──────────────────────────────────────────────────────────────────┤
│ □  Title            Priority  Due           Assignee  Related    │
│ ──────────────────────────────────────────────────────────────── │
│ □  Call Anil K.     high      Today 4 PM    Sarah K.  Lead       │
│ □  Send quote PDF   med       Tomorrow      You       Contact    │
│ ☑  Schedule visit   low       Done                    Lead       │
└──────────────────────────────────────────────────────────────────┘
```

- Header KPI strip: open / overdue / due-today counters with simple coloured dots (no chart).
- Filter chips: switch between `All` (org scope only) · `Mine` · `Overdue` · `Due today` · `Done`. Active chip highlighted.
- Search input (right-aligned in chip row): debounced 250 ms `q` filter on title.
- Table:
  - Checkbox column for quick complete.
  - Title (clickable → edit modal).
  - Priority (badge: gray / amber / rose).
  - Due (human relative: "Today 4 PM", "Tomorrow", "Yesterday", date for further).
  - Assignee name (resolved via `/users` lookup cached on init).
  - Related entity (text: "Lead" / "Contact" — links to the entity if we have the id).
- Pagination: simple "Showing N of M · [Load more]" — defer real pagination UI to v2.

## Scope discovery

On init the page calls `/api/v1/users/me`. If `permission_keys.includes('users.read')` → the `All` chip is rendered and active by default. Otherwise the `All` chip is hidden and the page defaults to `Mine`.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/tasks/tasks.page.ts` | created — standalone, OnPush |
| `app/src/app/features/user/core/tasks/tasks.page.html` | created |
| `app/src/app/features/user/core/tasks/task-form-modal.component.ts` | created — shared create + edit modal |
| `app/src/app/features/user/core/tasks/task-form-modal.component.html` | created |
| `app/src/app/features/user/core/tasks/tasks-api.service.ts` | modified — add `listAll(filters)` + extend `listMine(filters)` |
| `app/src/app/features/user/user.routes.ts` | modified — wire `/tasks` route |

**6 files. No backend changes (Step 1 already shipped). No new dependencies.**

## Generic filter shape

To keep the page small, share a single `TaskFilters` interface that both chips and search write to. One reactive signal; the load function reads it.

```ts
interface TaskFilters {
  scope: 'all' | 'mine';
  status?: 'open' | 'done' | 'cancelled';
  due_filter?: 'today' | 'overdue' | 'upcoming';
  priority?: 'low' | 'med' | 'high';
  q?: string;
  sort_by?: 'due_at' | 'priority' | 'title' | 'created_at';
  sort_dir?: 'asc' | 'desc';
}
```

Chip → filter mapping:
- `All` → `{ scope: 'all', status: 'open' }`
- `Mine` → `{ scope: 'mine', status: 'open' }`
- `Overdue` → `{ scope: <current>, due_filter: 'overdue', status: 'open' }`
- `Due today` → `{ scope: <current>, due_filter: 'today', status: 'open' }`
- `Done` → `{ scope: <current>, status: 'done' }`

Chip selection preserves current scope. Switching scope clears status to `open` (sensible default).

## Quick complete

The leftmost checkbox calls `PATCH /tasks/{id}` with `{ status: 'done' }` (or `{ status: 'open' }` to undo). On success, refresh from the backend (avoids local optimistic state drift). Disabled while the request is in flight.

## Create / edit modal

Single component reused for both modes. Fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| Title | text | ✓ | Max 255 |
| Description | textarea | – | |
| Due date | datetime-local | – | |
| Priority | select | ✓ | low / med / high |
| Assignee | select | ✓ | Populated from `/api/v1/users` (cached on page init); defaults to caller |
| Related to | dropdown + entity selector | – | v1: optional, free-text entity type + entity ID input. v2 polish: typeahead contact/lead picker. |

Submit:
- Create → `POST /tasks` → close + reload page.
- Edit → `PATCH /tasks/{id}` → close + reload page.

## Permission-driven UI

- The `Mine` scope is always visible.
- The `All` scope only appears when `currentUser.permissions().includes('users.read')`.
- The Create button is always visible — but submit will 403 if the user lacks `tasks.write`. We render an inline error in that case (extract via existing `extractApiError` util).

## Files to touch (route)

```ts
// user.routes.ts
{
  path: 'tasks',
  loadComponent: () =>
    import('./core/tasks/tasks.page').then((m) => m.TasksPageComponent),
}
```

No `permissionGuard` on the route — the page itself handles the scope branch. (The dashboard sets the precedent: every authenticated user can land on Tasks; what they see differs.)

## Smoke

```
ng build --configuration development   # clean build

# Manual via demo-logins pill:
# 1) Pick Core CRM — Owner → /user/tasks → All chip active, every org task visible.
# 2) Switch to "Mine" → list narrows to caller's own tasks.
# 3) Pick Core CRM — Employee → All chip is HIDDEN; default chip is "Mine".
# 4) Click [+ Create] → modal opens → fill title + priority → submit → row appears.
# 5) Click a row → modal opens in edit mode → change title → save → row updates.
# 6) Click the checkbox on an open row → row strikes through, moves out of the active filter.
# 7) Filter "Overdue" → only overdue rows.
# 8) Search "follow" → list narrows.
# 9) Sidebar Tasks click → lands on the page, no longer bounces to login.
```

## Risks

- **Assignee dropdown size on big orgs** — `GET /users` returns everyone in the org. For orgs over ~50 users this becomes unwieldy as a dropdown. v1 ships the dropdown; v2 swaps to typeahead. Not blocking.
- **Pagination MVP** — "Load more" is the v1 pattern. Real pagination (page numbers / infinite scroll) deferred. Limit defaults to 50 which covers most teams.
- **Optimistic UI on quick-complete** — currently we refetch after PATCH for simplicity. On slow networks this looks janky. v2 polish.
- **Related-entity v1 UX** — entity selector is rudimentary in v1 (free-text type + UUID input). Real typeahead is a v2 follow-up. For users creating tasks from the new page (rather than from a contact/lead detail), they'll mostly leave the field blank.
- **Caching `/users` for the assignee dropdown** — fetched once on page init and cached in a signal. If a user is added mid-session, the list is stale until refresh. Acceptable for v1.

## Rollback

Revert the 4 new files + 2 modified. Tasks sidebar entry goes back to bouncing through `/accounts/login` (the original broken state). Step 1's backend endpoint stays — harmless.
