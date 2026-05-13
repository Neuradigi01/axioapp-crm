# Step 3.5 — Staff module: frontend (admin view)

**Goal:** Staff Dashboard with the 7 tabs from the screenshots: Overview, Leaderboard, Targets & Commission, Attendance, Activity Log, Field Operations (placeholder until 4.10), Stock Updates (placeholder until 4.4), Store Marketing (placeholder until 5.6).
**Phase:** 3
**Depends on:** 3.4
**Status:** COMPLETED

## Scope
**In-scope:**
- `app/src/app/features/user/core/staff/`:
  - `staff-api.service.ts`
  - `staff.page.ts/.html` — tab host.
  - `tabs/overview.component.ts/.html`
  - `tabs/leaderboard.component.ts/.html`
  - `tabs/targets.component.ts/.html`
  - `tabs/attendance.component.ts/.html`
  - `tabs/activity.component.ts/.html`
  - `tabs/field-ops.component.ts/.html` — stub "Available after Phase 4.10"
  - `tabs/stock-updates.component.ts/.html` — stub
  - `tabs/store-marketing.component.ts/.html` — stub
- Tailwind only.

**Out of scope:**
- Adding/editing staff (uses existing user CRUD; UI for that comes later if requested).

## Files to touch
- `app/src/app/features/user/core/staff/*` (created)

## Plan
1. Tab host with signal-based active tab.
2. Each tab keeps its controller small (rule per master prompt).
3. Leaderboard sorts by performance.target_progress desc.
4. Targets tab shows commission_rate + monthly_target editor (admin only).
5. Attendance tab uses calendar component from 2.14.

## Verification checklist
**Frontend:**
- visit `/staff` → tabs visible; Overview shows summary cards.
- each tab loads independently; placeholder tabs render the explanatory note.

## Self-check (10 rules)
- [ ] No imports from `packs/`.
- [ ] Step ≤ ~12 files (each tab tiny).

## Stop & report
Await "proceed" before Step 3.6.
