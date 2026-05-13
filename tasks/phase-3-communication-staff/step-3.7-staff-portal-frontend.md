# Step 3.7 — Staff Portal: frontend

**Goal:** Separate route tree `/staff-portal`. Login screen with name picker + 4-digit PIN. After login: My Dashboard, Activity Log, Stock Updates (stub), Field Visits (stub until 4.10), My Attendance, My Sales tabs. Clock In/Out widget.
**Phase:** 3
**Depends on:** 3.6
**Status:** COMPLETED

## Scope
**In-scope:**
- `app/src/app/staff-portal/`:
  - `staff-portal.routes.ts` — separate guard `staff.guard.ts` (uses staff-token storage).
  - `staff-portal-shell.component.ts/.html` — minimal shell (no admin sidebar).
  - `login/login.page.ts/.html` — name list + PIN keypad.
  - `dashboard/my-dashboard.page.ts/.html`
  - `activity/activity-log.page.ts/.html`
  - `stock/stock-updates.page.ts/.html` — stub
  - `field/field-visits.page.ts/.html` — stub
  - `attendance/my-attendance.page.ts/.html` — clock-in/out + history.
  - `sales/my-sales.page.ts/.html`
- Separate token storage key: `staff_access_token` (so admin login doesn't collide).
- Tailwind only. Mobile-first layout (this is for tablets).

## Files to touch
- `app/src/app/staff-portal/*` (created)
- `app/src/app/app.routes.ts` (modified — add staff-portal sibling routes)

## Plan
1. Routes registered as `/staff-portal/...`. Shell + child routes.
2. Login page: fetches user list by `org_slug` from a config; PIN keypad component.
3. After login: route to `dashboard`. Each tab loads independently.
4. Clock-in/out widget visible globally on the portal shell (top bar).

## Verification checklist
**Frontend:**
- visit `/staff-portal/login` → user picker.
- enter wrong PIN 6× → toast "Try again later".
- correct PIN → routes to dashboard.
- clock-in → button toggles; clock-out updates hours.

## Self-check (10 rules)
- [ ] Separate token storage key.
- [ ] Tailwind only.

## Stop & report
Await "proceed" before Step 3.8.
