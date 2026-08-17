# Step 4 — Frontend: Follow-Up History panel on lead-detail page

**Goal:** Ship the "Follow-Up Status" table sir's screenshot shows below the Update Status modal. Panel lives on the lead-detail page (Overview tab, under the header), lists this lead's tasks with `related_entity_type='lead'` newest-due-first, and lets the rep mark done / reschedule inline — reusing the same UI patterns as the dashboard's Today's Follow-ups widget.
**Track:** Leads — Update Status Flow
**Status:** Pending
**Depends on:** Step 3 (modal writes tasks via `POST /tasks`); existing `TasksApiService` in the FE.

---

## Scope

In-scope:

- New standalone `LeadFollowUpsPanelComponent` that:
  - On init, calls `TasksApiService.list({related_entity_type: 'lead', related_entity_id: lead.id, status: 'open,missed'})` — reuses the existing endpoint.
  - Renders a table with columns: **Due** (date + relative — "in 2 days", "overdue by 4 days"), **Status** pill (Open / Missed), **Type** (call/whatsapp/email/document/meeting/other with matching lucide icon), **Title**, **Actions** (Mark done, Reschedule).
  - Empty state: "No follow-ups scheduled. Use Update Status to schedule one."
  - Pagination: 20 per page + "Load more" button (server supports cursor pagination — verify in step-4 spike). If the lead has < 20 follow-ups it renders as one page.
  - Mark done: calls `TasksApiService.bulkMarkDone([taskId])` (existing), optimistically removes the row (or moves to a Done section — see plan step 4).
  - Reschedule: inline datetime input opens; POST `PATCH /tasks/{id}` with new `due_at` (verify method name on the FE service; if it's `update` use that).
- Public method `prepend(task: Task): void` on the component so the parent can add the newly-created task after an Update Status submit without refetching.
- Yellow/orange section header (mirrors sir's screenshot color) — Tailwind `bg-amber-500/10` container with `text-amber-700` header text.
- Panel renders on the Overview tab, below the header block, above the tabs. Alternative: on the Activities tab. **My call: Overview.** Rationale: sir's screenshot places it directly under the modal on the primary lead view; Activities tab is for the full timeline (includes notes/calls/status-changes), not a filtered follow-up cut.

Out of scope:

- No new API endpoint. Uses existing `GET /tasks` and mutation endpoints.
- No dashboard-widget changes.
- No "Done" tasks section — tasks the rep marked done leave the panel (still visible in the full activities timeline via the `task` activity type once step 4 of task-completion emits it — that's already the case).
- No editing task title in place. Title is set at creation time via the Update Status modal.
- No cancel-task action. Reps mark done or leave overdue.

## DB changes / migrations

**None.**

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/leads/lead-follow-ups-panel.component.ts` | created |
| `APP/src/app/features/user/core/leads/lead-follow-ups-panel.component.html` | created |
| [`APP/src/app/features/user/core/leads/lead-detail.page.html`](../../APP/src/app/features/user/core/leads/lead-detail.page.html) | modified — mount `<app-lead-follow-ups-panel [lead]="l()">` inside Overview tab |
| [`APP/src/app/features/user/core/leads/lead-detail.page.ts`](../../APP/src/app/features/user/core/leads/lead-detail.page.ts) | modified — add `viewChild(LeadFollowUpsPanelComponent)` so `onLeadSaved()` from step 3 can call `.prepend(newTask)` |

**4 files, ~250 LOC.** Inside rule-8.

## Plan

1. **Verify FE tasks-api surface.** Confirm `TasksApiService.list()` accepts `related_entity_type` + `related_entity_id` filters and returns paginated. If not, add the params (small: 1 file, 5 LOC).
2. **Component shape.** Standalone, OnPush. Inputs: `lead: Lead` (signal). Internal signals: `tasks`, `loading`, `error`, `nextCursor`, `mutating` (per-task set).
3. **On init effect.** `effect(() => { const l = this.lead(); if (!l) return; this.load(l.id); })`. Load calls the API with `status IN (open,missed)`, sort `due_at asc` — earliest overdue at top, then future in order.
4. **Mark done** — optimistic. On click, set `mutating.add(taskId)`, call `bulkMarkDone([taskId])`. On 200 remove from local `tasks` array. On error rollback + show inline red text on that row for 4 seconds.
5. **Reschedule** — inline datetime input replaces the Due column for that row. Confirm button → `TasksApiService.update(taskId, {due_at: newValue})` (mirrors modal's payload validation: bounded to now-1y..now+5y). Cancel button reverts. On success update the task in place + re-sort.
6. **`prepend(task)` public method.** `this.tasks.update(list => [task, ...list])`.
7. **Template.**
   ```html
   <section class="mt-4 rounded-lg border border-subtle overflow-hidden">
     <header class="bg-amber-500/10 px-4 py-2 text-sm font-semibold text-amber-700 uppercase tracking-wider">
       Follow-Up Status
     </header>
     <div class="p-4">
       @if (loading()) { <skeleton /> }
       @else if (error(); as e) { <p class="text-red-500">{{ e }}</p> }
       @else if (tasks().length === 0) { <p class="text-muted text-sm">No follow-ups scheduled. Use Update Status to schedule one.</p> }
       @else {
         <table>...</table>
         @if (nextCursor()) { <button (click)="loadMore()">Load more</button> }
       }
     </div>
   </section>
   ```
8. **Wire to lead-detail** — in `lead-detail.page.html`, mount the panel inside the Overview tab's container. In `lead-detail.page.ts`, wire the viewChild ref and call `panel().prepend(task)` inside `onLeadSaved` when `next_follow_up_task_id` is present in the response.

## Tests

Unit:

1. **Empty state** — component with no tasks renders the empty-state text.
2. **Renders overdue with negative relative-time** — task with `due_at` in the past shows "overdue by X days" in red.
3. **Renders future with positive relative-time** — "in 2 days".
4. **Mark done optimistic removal** — click → row removed immediately; on API error → row reappears with red flash.
5. **Reschedule inline** — click reschedule → datetime input appears; confirm with a new date → row updates in place + re-sorts.
6. **`prepend()` public method** — after `prepend(newTask)`, the new task appears at position 0 (or in date-sorted position — decide based on the sort direction; recommend prepend then re-sort by due_at).
7. **Load more** — server returns `next_cursor` → button visible; click → appends next page.

Manual smoke:

8. Open a lead in Ajay's Workspace with no follow-ups. Panel shows empty state. Click Update Status, schedule a follow-up for tomorrow 10:00. Modal closes. Panel now shows one row: "Tomorrow 10:00 · Open · Call · Follow up: <remarks>". Click Mark done → row disappears. Refresh → still gone (persisted). Dashboard "Today's Follow-ups" widget → "Completed today" count incremented.

## Smoke

```powershell
cd APP; npm start
# Browse to lead detail; verify per test #8.

# Prettier format
npx --no-install prettier --write src/app/features/user/core/leads/lead-follow-ups-panel.component.ts src/app/features/user/core/leads/lead-follow-ups-panel.component.html src/app/features/user/core/leads/lead-detail.page.html src/app/features/user/core/leads/lead-detail.page.ts
```

## Risks

- **Duplication with dashboard follow-ups widget.** The dashboard widget reads the same table; risk of divergent rendering. Mitigation: extract a shared `<crm-followup-row>` sub-component in a *future* small refactor if drift emerges. Not required in this step — the two surfaces have different scopes (lead-scoped table vs org-wide bucket-grouped list) and copying ~50 LOC now is cheaper than premature abstraction.
- **Cursor pagination format** — verify FE tasks-api returns `{items, next_cursor}` vs `{items, total}`. Adjust the "Load more" wiring to whichever shape it returns; if offset-based, use page numbers instead. Small.
- **Timezone drift on reschedule** — same as step 3: convert local datetime to UTC ISO before POST; back to local for display.
- **Overview tab vs Activities tab placement** — sir's screenshot is unambiguous about placement below the modal, which our detail page's Overview tab most matches. If the manager prefers Activities, a one-line template move; no code change needed.

## Rollback

Revert the four files.
