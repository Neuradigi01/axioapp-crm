# Step 12 — Appointments refresh

**Goal:** Restyle the appointments module — both list view and calendar view.
**Track:** Design Refresh — Track 4 (Page pass)
**Status:** COMPLETED — all 4 appointments HTML files bulk-swapped to AIXO semantic tokens: appointments.page (list + calendar), book-appointment-modal, appointment-popover, reschedule-modal. Chrome + event chips now teal-accent themed; existing calendar library reused. `ng build` green.
**Depends on:** Steps 1, 5, 6, 7

---

## AIXO patterns

### List view
- Same page-header + table pattern as Contacts (Step 9).
- Columns: title / contact / start / duration / owner / status. Status pill uses semantic status colors.

### Calendar view
- Header: month/week/day segmented + prev/today/next buttons + "+ New" primary.
- Grid: month view uses 7-col grid, cells `rounded-lg` `border-subtle` 1px. Today cell: `bg-accent-soft` `text-accent` border.
- Event chip inside a cell: `rounded-md` 6px, 2px 6px padding, 11.5px, `bg-accent-soft` `text-accent` for accent events; per-owner colors optional.

### Appointment detail modal (from Step 7)
- 480px width, AIXO modal look. Fields: title / contact link / date / start-end / recurrence / attendees / notes / status.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/appointments/appointments-list/*.{ts,html}` | modified |
| `APP/src/app/features/user/core/appointments/appointments-calendar/*.{ts,html,scss}` | modified |
| `APP/src/app/features/user/core/appointments/appointment-form/*.{ts,html}` | modified |
| `APP/src/app/features/user/core/appointments/appointment-detail/*.{ts,html}` | modified |

**~6–8 files.**

## Verification

- List view + calendar view both render correctly.
- Toggling views preserves the selected date range.
- Detail modal opens with new look.

## Out of scope

- New calendar library — reuse the current one.
- Sync with Google Calendar UI — future track.
