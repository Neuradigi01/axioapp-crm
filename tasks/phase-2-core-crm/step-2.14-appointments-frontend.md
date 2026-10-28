# Step 2.14 — Appointments: frontend

**Goal:** Appointments page with monthly calendar matching the screenshot. Day-detail panel on the right. "Book Appointment" modal. Reusable `<app-calendar>` component.
**Phase:** 2
**Depends on:** 2.13, 2.4
**Status:** COMPLETED

## Scope
**In-scope:**
- `app/src/app/features/user/core/appointments/`:
  - `appointments-api.service.ts`
  - `appointments.page.ts/.html` — month grid + right panel.
  - `book-appointment-modal.component.ts/.html` — contact picker, purpose, scheduled_at, duration, location, assigned_to.
- `app/src/app/features/user/core/shared/calendar/`:
  - `calendar.component.ts/.html` — month view with day cells, dot indicators per appointment, click → emits `(daySelected)`.
- Tailwind only. No external date library beyond `date-fns` (small).

**Out of scope:**
- Week/day views — later.
- Field-visit specifics — Phase 4.

## Files to touch
- `app/src/app/features/user/core/appointments/*` (created)
- `app/src/app/features/user/core/shared/calendar/*` (created)
- `app/package.json` (modified — `date-fns`)
- `app/src/app/app.routes.ts` (modified)

## Plan
1. Calendar component: signal for `viewMonth`. Render 7×6 grid using `date-fns/eachDayOfInterval`.
2. Inputs `(events: {date, count, items}[])`. Render dots/badges.
3. Page: fetch month range on viewMonth change. Right panel lists appointments for selected day.
4. Book modal: validate scheduled_at + duration; on 409 show conflict toast and highlight the conflicting time.

## Verification checklist
**Frontend:**
- visit `/appointments` → month grid with current month.
- create appointment → dot appears on the day; clicking day shows in panel.
- attempt conflicting → toast "Time conflict" with link.

## Self-check (10 rules)
- [ ] Reusable calendar; no domain-specific logic in it.

## Stop & report
Await "proceed" before Step 2.15.
