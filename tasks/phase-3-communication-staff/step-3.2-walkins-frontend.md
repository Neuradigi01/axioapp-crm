# Step 3.2 — Walk-ins: frontend

**Goal:** Walk-in Customers page matching the screenshot — register modal uses `<app-dynamic-form>`, status filters, today's stats cards, conversion rate.
**Phase:** 3
**Depends on:** 3.1, 2.3
**Status:** Pending

## Scope
**In-scope:**
- `app/src/app/features/user/core/walk-ins/`:
  - `walk-ins-api.service.ts`
  - `walk-ins.page.ts/.html` — stats row + filter chips + table.
  - `register-walkin-modal.component.ts/.html` — quick-register form using dynamic-form for custom fields.
- KPI cards: today's walk-ins, currently in store, converted today, conversion rate %.
- Tailwind only.

## Files to touch
- `app/src/app/features/user/core/walk-ins/*` (created)
- `app/src/app/app.routes.ts` (modified)

## Plan
1. API service.
2. Page with signals; stats endpoint added in 3.1 service if not present (else compute client-side from list).
3. Register modal: contact picker with auto-fill on phone match.
4. Status badges per spec.
5. Checkout button on row sets time_out.

## Verification checklist
**Frontend:**
- visit `/walk-ins` → stats cards + table.
- register → row appears in "browsing" status.
- check-out → duration shown.

## Self-check (10 rules)
- [ ] Form fields dynamic.
- [ ] Tailwind only.

## Stop & report
Await "proceed" before Step 3.3.
