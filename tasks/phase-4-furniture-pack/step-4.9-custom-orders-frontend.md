# Step 4.9 — Custom Orders — frontend

**Goal:** Custom Orders page with status filters, card view matching the screenshot. New Custom Order modal with measurements (L/W/H), materials, color, photos, special requirements.
**Phase:** 4
**Depends on:** 4.8, 2.10, 2.3
**Status:** COMPLETED

## Scope
**In-scope:**
- `app/src/app/features/user/packs/furniture/custom-orders/`:
  - `custom-orders-api.service.ts`
  - `custom-orders.page.ts/.html` — pipeline view + list view (toggle); reuses `<app-pipeline-board pipelineKey="custom_orders">`.
  - `custom-order-card.component.ts/.html`
  - `custom-order-form-modal.component.ts/.html` — multi-step: contact picker → product details → measurements (multi-row) → photos → review.
  - `custom-order-detail.page.ts/.html` — full info with photo gallery, measurement table, stage history.
- Tailwind only.

## Files to touch
- `app/src/app/features/user/packs/furniture/custom-orders/*` (created)
- `app/src/app/app.routes.ts` (modified)

## Plan
1. API service.
2. Multi-step modal: each step a small component to keep controllers small.
3. Photo upload preview before submit; submit uploads after order is created.
4. Detail page: stage history timeline reused via core activity-timeline component.

## Verification checklist
**Frontend:**
- visit `/custom-orders` → kanban with 6 stages.
- create order with 2 measurements + 3 photos → appears in `measurement_scheduled`.
- drag to next stage → persists; activity logged.

## Self-check (10 rules)
- [ ] Reuses pipeline-board (no duplicated kanban).

## Stop & report
Await "proceed" before Step 4.10.
