# Step 3 — Reschedule modal + bulk reassign / bulk cancel + row ergonomics (tel / mail / WhatsApp, URL state)

**Goal:** complete the appointments worklist. Add a focused Reschedule modal (date / time + optional reason) without forcing the full edit form. Wire bulk reassign + bulk cancel. Apply phone / email link directives to the linked-contact info on each row. Round-trip filters in the URL.

**Depends on:** Step 2 + `update-contacts-page/` Steps 3–4 shared primitives.

## Files changed

### Modified backend
- `API/src/app/core/appointments/router.py` — add `POST /appointments/{id}/reschedule`, `POST /appointments/{id}/reassign`, `POST /appointments/bulk-reassign`, `POST /appointments/bulk-cancel`.
- `API/src/app/core/appointments/service.py` — `reschedule_appointment`, `reassign_appointment`, `bulk_reassign_appointments`, `bulk_cancel_appointments`.
- `API/src/app/core/appointments/schemas.py` — `AppointmentReschedule`, `AppointmentReassign`, `AppointmentBulkReassign`, `AppointmentBulkCancel`.

### New frontend
- `APP/src/app/features/user/core/appointments/reschedule-modal.component.ts`
- `APP/src/app/features/user/core/appointments/reschedule-modal.component.html`
- `APP/src/app/features/user/core/appointments/appointment-popover.component.ts`
- `APP/src/app/features/user/core/appointments/appointment-popover.component.html`

### Modified frontend
- `APP/src/app/features/user/core/appointments/appointments-api.service.ts` — `reschedule`, `reassign`, `bulkReassign`, `bulkCancel`.
- `APP/src/app/features/user/core/appointments/appointments.page.ts` — selection state, URL state, bulk handlers.
- `APP/src/app/features/user/core/appointments/appointments.page.html` — checkbox column, BulkActionBar, modals mount, calendar event-click → popover.

### Tests
- `API/tests/core/appointments/test_reschedule_and_bulk.py` (new)

## Backend — endpoints

- `POST /appointments/{id}/reschedule` — body `{"scheduled_at": "<iso>", "reason": "<string|null>"}`. Requires `appointments.write`. Writes an audit activity `type='reschedule'` with `body={"from":..., "to":..., "reason":...}`. Bumps `last_activity_at`.
- `POST /appointments/{id}/reassign` — body `{"assigned_to_id": uuid|null}`. `appointments.reassign`. Audit + bump.
- `POST /appointments/bulk-reassign` — max 200 ids. `appointments.reassign`.
- `POST /appointments/bulk-cancel` — max 200 ids. `appointments.write`. Per-row state-machine check (only `scheduled` → `cancelled`); per-row errors aggregated.

## Frontend — `reschedule-modal.component`

Inputs: `appointment`.

Body:
- Date picker (default = current scheduled_at).
- Time picker (default = current scheduled_at hour/min).
- Optional textarea "Reason for reschedule" (saved on audit activity).
- Cancel / Save.

On confirm → `api.reschedule(id, { scheduled_at, reason })` → parent refresh.

## Frontend — `appointment-popover.component`

Anchored to a calendar event or a row's actions column. Shows action buttons:
- **Reassign** (gated `appointments.reassign`) → opens shared `ReassignModal`.
- **Reschedule** (gated `appointments.write`) → opens `RescheduleModal`.
- **Mark completed** (gated `appointments.write`) → inline state-machine call.
- **Cancel** (gated `appointments.write`) → inline call with confirm.

Use the same component on both views — keeps interaction consistent.

## `appointments.page.ts` — URL state + selection

```typescript
readonly urlState: UrlFilterStateConfig = {
  view: { signal: this.view, queryKey: 'view' },
  status: { signal: this.statusFilter, queryKey: 'status' },
  assigned_to_id: { signal: this.assigneeSignal, queryKey: 'assignee' },
  scope: { signal: this.scope, queryKey: 'scope' },
  sort: { signal: this.sortKey, queryKey: 'sort' },
  order: { signal: this.sortOrder, queryKey: 'order' },
  scheduled_from: { signal: this.scheduledFrom, queryKey: 'from' },
  scheduled_to: { signal: this.scheduledTo, queryKey: 'to' },
  page: { signal: this.page, queryKey: 'page' },
};
```

Selection state matches contacts/leads/walk-ins pattern. Bulk actions: Reassign / Cancel.

## Row ergonomics

- Linked-contact phone wrapped with `[appPhoneLink]`; WhatsApp icon `[appWhatsappLink]`.
- Email wrapped with `[appMailLink]`.
- Replace `window.confirm` paths with `<app-confirm-dialog>`.

## Test `test_reschedule_and_bulk.py`

1. Reschedule shifts `scheduled_at` + writes audit + bumps `last_activity_at`.
2. Reschedule a completed appointment → 422 (state).
3. Bulk cancel 3 scheduled → all 3 cancelled, 3 audit activities.
4. Bulk cancel includes one non-scheduled → partial success in response.

## Acceptance

1. List view: checkbox column + bulk reassign / cancel.
2. Calendar view: click event → popover with Reassign / Reschedule / Mark completed / Cancel.
3. Reschedule modal works from any context.
4. Linked-contact phone / email links work.
5. URL round-trips view + filters.
6. Junior sees no reassign / no bulk-cancel.

## Lucide icons used

`calendar-clock` (reschedule), `x-circle` (cancel), `check-circle-2`, `pencil`, `user-cog`. Verify registry.

## Self-check vs the 10 rules

- ✅ Rule 1 — appointments composes Layer 1 only.
- ✅ Rule 8 — 10 files; right at limit.
- ✅ Rule 10 — reschedule + bulk cancel ship complete with audit and state-machine checks.

## Stop-and-report template

> ✅ Step 3 complete. Appointments track done.
> **Files changed:** 10.
> **What you can verify:**
> 1. Reschedule modal from list, calendar event popover, and detail.
> 2. Bulk reassign + bulk cancel.
> 3. Linked-contact tel / WhatsApp / mail.
> 4. URL state preserves view + filters.
> 5. Calendar event popover offers all four actions, gated by permission.
> **Tests added:** `test_reschedule_and_bulk.py` (4).
> **Self-check:** all 10 rules ✅.
> **Appointments track complete.** Recommend proceeding to `update-tasks-page/`.
