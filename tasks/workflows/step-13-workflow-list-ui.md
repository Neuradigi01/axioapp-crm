# Step 13 — Workflow list UI + folders/categories

**Goal:** First Angular surface — `/user/workflows` list page with channel/category/status filters, folders sidebar, status badges, per-row analytics summary, "Create from template" CTA, and "New workflow" button. Mirrors `/user/templates` and `/user/campaigns` styling.
**Status:** Pending
**Depends on:** Step 3 (router endpoints + sidebar entry + permission `workflows.read`).

---

## Scope

In-scope:

- `app/src/app/features/user/core/workflows/workflows-api.service.ts`:
  - Typed HttpClient wrappers for the Step 3 + Step 4 endpoints (list / get / create / patch / archive / activate / pause / clone / folder CRUD / runs / step_runs).
  - Shared types: `WorkflowRead`, `WorkflowSummary`, `WorkflowFolder`, `WorkflowRunRead`, `WorkflowStepRunRead`, `WorkflowGraph` (loose at this step; Step 14 + 15 tighten to typed node shapes).

- `app/src/app/features/user/core/workflows/workflows.page.{ts,html}`:
  - Two-column layout: folders sidebar (collapsible) + workflows grid/list.
  - Filters row: channel (multi-select chip), category (Sales / Marketing / Service / Internal / Custom), status (Draft / Active / Paused / Archived), search box (debounced 300ms).
  - Workflows are shown as cards (per-row summary view): name, status badge, category chip, last-edit timestamp, "running now" count (open runs), "completed this week" count, "goal-conversion" mini sparkline (Step 19 expands; Step 13 shows the static count).
  - Row CTA: Edit (opens Step 14 canvas), Run history (drawer with Step 4 endpoints), More (clone, archive, view JSON). Bulk select with "activate / pause / archive selected".
  - Empty state: "No workflows yet. Start from a template, or build your own." Two CTAs side-by-side.

- `app/src/app/features/user/core/workflows/folders/`:
  - `folders-sidebar.component.{ts,html}` — drag-drop to reorder, right-click to rename, "New folder" button. Reuses the existing `@angular/cdk/drag-drop` peer dep.
  - `folder-create.modal.component.{ts,html}` — name + parent picker.

- `app/src/app/features/user/core/workflows/workflow-status-badge.component.ts`:
  - Color palette: `draft` zinc, `active` emerald, `paused` amber, `archived` zinc-light. Mirrors template-status-badge component palette.

- `app/src/app/features/user/core/workflows/run-history-drawer.component.{ts,html}`:
  - Side drawer (right-anchored). Shows the workflow's last 50 runs (paginated). Each row: started_at, contact name (from contact_id lookup), status badge, current_node label, step count completed/total, outcome chip. Click a row → expands the step timeline (uses Step 4's GET /runs/{run_id}/steps).

- Lazy route: `/user/workflows` → `WorkflowsPageComponent`. Guarded by `permissionGuard('workflows.read')`.

- Sidebar registration consumed (no edit — Step 3 registered it at the backend).

Out of scope:

- Canvas editor (Step 14).
- Node editor drawer (Step 15).
- Templates gallery (Step 16).
- Analytics dashboard (Step 19 — the per-row mini stats here are static counts, not interactive charts).
- Diagnostics tool (Step 19).
- A/B test comparison view (Step 18).

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/workflows/workflows-api.service.ts` | **NEW** |
| `APP/src/app/features/user/core/workflows/workflows.page.{ts,html,spec.ts}` | **NEW** |
| `APP/src/app/features/user/core/workflows/folders/folders-sidebar.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/folders/folder-create.modal.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/workflow-status-badge.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/run-history-drawer.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/user.routes.ts` | edit — lazy route to `/user/workflows` |
| `APP/src/app/app.config.ts` | edit — register Lucide icons (`workflow`, `git-branch`, `folder`, `folder-plus`, `archive`, `play`, `pause`) |

**~12 files. ~700 lines.**

## Plan

1. API service first.
2. Workflows list page with filters + grid.
3. Folder sidebar + folder-create modal.
4. Status badge component.
5. Run-history drawer.
6. Routes + icons.
7. Specs (4 Jest cases).

## DB changes / migrations

None.

## Tests

4 Jest cases in `workflows.page.spec.ts`:

- Renders empty state when API returns no rows.
- Channel filter calls `api.list` with `channel='whatsapp'`.
- Status filter cascades — selecting `active` then `paused` returns OR-joined rows.
- Permission gate: Employee role hides "New workflow" button.

## Smoke

```
1. /user/workflows → empty state → "Start from template" + "New workflow" CTAs visible.
2. Create a folder "Sales" → appears in sidebar.
3. Create a workflow (POST /workflows from console for now) → row appears in the grid with Draft badge.
4. Click filter chips: Channel=WhatsApp → only WA workflows shown.
5. Click row → opens canvas (Step 14 — placeholder route until then).
6. Right-click row → Clone → creates a draft duplicate.
7. Bulk-select 2 rows → "Archive selected" → both flip to Archived.
8. Click "Run history" on a workflow row → drawer opens; recent runs visible.
```

## Risks

- Drag-drop folder reordering with nested folders — recursion limit at depth 3 (operators rarely need deeper). Document in the folder-create modal.
- Workflows list grows large (>500) — pagination at 50 per page; server-side filtering already covers it.
- "Running now" count is a cheap-ish query but could be hot. Step 19 caches it in `tbl_workflows.cached_running_count` updated via a 5-minute beat sweep.

## Self-check (10 rules)

`core/workflows/` frontend only. ✓ org_id transparent via API. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ Sidebar entry registered upstream. Permissions checked client + server. pack.yaml untouched. ✓ 12 files / ~700 lines — over but justified (list page + folder UI + drawer + badge + service). Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 13 — Workflow list UI + folders/categories
Files: 12
Verify: list page renders with filters; folder sidebar functional; status badges colored; run-history drawer shows recent runs; permission gates hide write CTAs for read-only users.
Tests: 4 Jest cases.
Awaiting "proceed".
```
