# Step 3.12 — Call Center: frontend

**Goal:** Five tabs from the screenshots: Call Logs, Phone Book, Transcripts, Book Appointment, Analytics. Reuse existing components where possible.
**Phase:** 3
**Depends on:** 3.11, 2.14
**Status:** Pending

## Scope
**In-scope:**
- `app/src/app/features/user/core/calls/`:
  - `calls-api.service.ts`
  - `call-center.page.ts/.html` — tab host.
  - `tabs/logs.component.ts/.html` — table of calls.
  - `tabs/phone-book.component.ts/.html` — searchable contacts with click-to-call.
  - `tabs/transcripts.component.ts/.html` — list + transcript viewer.
  - `tabs/book-appointment.component.ts/.html` — wraps BookAppointmentModal from 2.14.
  - `tabs/analytics.component.ts/.html` — three charts (use a small library like `chart.js` via `ng2-charts`).
- Tailwind only.

## Files to touch
- `app/src/app/features/user/core/calls/*` (created)
- `app/package.json` (modified — `chart.js`, `ng2-charts`)

## Plan
1. API service.
2. Each tab keeps its controller small.
3. Analytics tab: three chart components (donut for outcomes, bar for daily, donut for direction).
4. Click-to-call: opens `tel:<phone>` and pre-fills a "log this call" modal.

## Verification checklist
**Frontend:**
- visit `/calls` → tabs.
- log a call → appears in Logs.
- analytics shows charts.

## Self-check (10 rules)
- [ ] Reuses existing modals/components.

## Stop & report
Await "proceed" before Step 3.13.
