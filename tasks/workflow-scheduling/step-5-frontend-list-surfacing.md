# Step 5 — Frontend — schedule surfacing in workflow list + pause/resume/delete

**Goal:** Surface schedules in the main workflows list page: new "Next Run" column, "Scheduled" filter chip, per-row schedule count badge. Add pause/resume/delete actions inline (either as icon buttons or a menu). No new page; extends the existing list.

**Status:** Pending

**Depends on:** Step 4 (schedule attach panel exists so users can create schedules to see here)

---

## Scope

**In-scope:**
- Extend `workflows/list-page.component`:
  - New column "Next Run" — shows earliest `next_run_at` across the workflow's active schedules, in the org's timezone. Empty for unscheduled workflows.
  - New column "Schedules" — small pill showing count (e.g. "2 active") or nothing.
  - New filter chip "Scheduled" — filters list to workflows with at least one active schedule.
- Row actions extension:
  - "Manage schedules" → navigates to detail page's schedule panel (Step 4).
  - "Pause all schedules" / "Resume all schedules" bulk action per workflow (calls pause/resume in a loop; toast summary).
- Delete action stays on the schedule (not workflow) — inside the attach panel from Step 4. Nothing new here.
- List API: extend the existing workflow list DTO to include `active_schedule_count` and `next_scheduled_at` (backend concern — small addition; may require touching Step 3's list serializer or a small follow-up in the workflow list endpoint).

**Out-of-scope:**
- Bulk pause across ALL workflows in the org (open item §6 in README).
- New page.
- Sidebar changes.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/workflows/list-page.component.html` | edit — add columns + filter chip + row action |
| `app/src/app/features/user/core/workflows/list-page.component.ts` | edit — filter state, action handlers, wire toast |
| `app/src/app/features/user/core/workflows/workflows.service.ts` | edit — extend list method to accept `has_schedule` filter; add `pauseAllForWorkflow`, `resumeAllForWorkflow` |
| `app/src/app/features/user/core/workflows/models.ts` | edit — extend `WorkflowListRow` with `active_schedule_count`, `next_scheduled_at` |
| `api/src/app/core/workflows/router.py` | edit — extend list endpoint to accept `has_schedule` query param + populate `active_schedule_count` + `next_scheduled_at` in response |
| `api/src/app/core/workflows/schemas.py` | edit — extend `WorkflowListItemResponse` |
| `api/src/app/core/workflows/data_access.py` | edit — extend list query to `LEFT JOIN LATERAL (SELECT ... FROM tbl_workflow_schedules ...)` for count + min next_run_at in ONE query (no N+1) |
| `api/tests/workflows/test_workflow_list_with_schedules.py` | **NEW** — 4 cases: unscheduled workflow shows nulls; scheduled shows count + min next_run_at; filter chip narrows correctly; N+1 sanity (single query for N workflows) |

**~8 files, ~350 lines.**

## Plan

1. **Backend list query extension** — modify list DAL to include the schedule subquery. `LEFT JOIN LATERAL (SELECT COUNT(*), MIN(next_run_at) FROM tbl_workflow_schedules s WHERE s.workflow_id = w.id AND s.active = true) sched ON TRUE`. Adds one join, keeps query cost O(workflows).
2. **DTO extension** — new fields in `WorkflowListItemResponse`.
3. **Filter param** — `has_schedule: bool | None` → adds `WHERE ... AND (sched.count > 0)` when true.
4. **Frontend columns** — Tailwind cells; empty-friendly rendering.
5. **Filter chip** — add to existing filter row.
6. **Bulk pause/resume per workflow** — service method loops schedules and calls pause/resume; result summarized in a toast ("3 paused, 1 already paused"). Not a bulk DB update — sequential to respect per-endpoint audit.
7. **Prettier + lint** before stop-report.
8. **Tests** — backend pytest (list-with-schedules); frontend Karma optional (list columns are cosmetic).

## Verification

- Workflows list shows Next Run column populated for scheduled workflows, empty for others.
- Filter "Scheduled" narrows the list to workflows with active schedules.
- "Pause all schedules" on a workflow with 3 active schedules → all 3 paused, toast "3 paused"; row's next-run cell now empty.
- Backend query test proves no N+1.
- Prettier + lint clean.

## Stop-and-report template

```
Step 5 done — schedules surfaced in workflow list + bulk pause/resume.

Files changed: <list>
What you can verify:
  - Workflows list shows Next Run + Schedules columns
  - "Scheduled" filter chip narrows the list
  - Bulk pause on a workflow pauses all its schedules
  - EXPLAIN ANALYZE on list query shows single scan (no N+1)
Tests added: ~4 backend cases
Self-check: [pass/fixed/N/A on 10 rules · layering · reuse · DB efficiency · tooling-clean · prettier]
Awaiting your 'proceed' for Step 6.
```
