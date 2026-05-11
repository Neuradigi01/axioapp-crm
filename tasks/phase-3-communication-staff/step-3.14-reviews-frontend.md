# Step 3.14 — Reviews: frontend

**Goal:** Reviews & Reputation page matching the screenshot — rating distribution, negative-review alerts, reply functionality, auto-request toggle, star filters.
**Phase:** 3
**Depends on:** 3.13
**Status:** Pending

## Scope
**In-scope:**
- `app/src/app/features/user/core/reviews/`:
  - `reviews-api.service.ts`
  - `reviews.page.ts/.html` — KPI cards + alerts panel + filterable list.
  - `reply-modal.component.ts/.html`
- Tailwind only.

## Files to touch
- `app/src/app/features/user/core/reviews/*` (created)

## Plan
1. KPI: avg rating, total, response rate, ≤3-star alerts.
2. Star filters (1–5) toggle list.
3. Reply modal: textarea + send.
4. Auto-request toggle stored in Settings (ref Step 3.17 — for now writes to `settings/reviews-auto-request`).

## Verification checklist
**Frontend:**
- visit `/reviews` → distribution + list.
- click reply → modal → submit → status changes.
- filter by 1-star → list narrows.

## Self-check (10 rules)
- [ ] No hardcoded source-specific UI; works for any `source` value.

## Stop & report
Await "proceed" before Step 3.15.
