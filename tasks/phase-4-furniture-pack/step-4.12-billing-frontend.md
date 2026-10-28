# Step 4.12 — Furniture: Billing / POS — frontend

**Goal:** Billing & POS page with Invoices and POS tabs matching screenshots. POS screen with cart, customer details, discount (flat/percent), payment method picker, bill summary, Print Bill.
**Phase:** 4
**Depends on:** 4.11
**Status:** COMPLETED

## Scope
**In-scope:**
- `app/src/app/features/user/packs/furniture/billing/`:
  - `billing-api.service.ts`
  - `billing.page.ts/.html` — tab host (Invoices + POS).
  - `tabs/invoices.component.ts/.html` — list with status filters, click → detail.
  - `invoice-detail.page.ts/.html` — full invoice with payments + Print/PDF button.
  - `tabs/pos.component.ts/.html` — left: catalog grid + cart; right: customer + discount + payment + total + Pay & Print.
- Tailwind only.

## Files to touch
- `app/src/app/features/user/packs/furniture/billing/*` (created)
- `app/src/app/app.routes.ts` (modified)

## Plan
1. POS layout: signal-based cart `lines = signal<CartLine[]>([])`. Add by clicking catalog item; +/- buttons for qty.
2. Discount: flat or percent toggle. Live total recomputes.
3. Payment method picker: cash/card/upi/emi/cheque/bank (icons).
4. Pay → calls `/pos/checkout` → opens PDF in new tab.
5. Customer: phone first; auto-fill if found, else inline create.

## Verification checklist
**Frontend:**
- visit `/billing` → tabs.
- POS: add 2 items, set qty, apply 10% discount, choose UPI, Pay → PDF opens; invoice appears in Invoices tab.
- inventory decremented (verify on inventory page).

## Self-check (10 rules)
- [ ] No imports from `core/` *into* the pack? — opposite is allowed; pack imports core. Confirm pack doesn't accidentally pollute core (no edits to core under this step).
- [ ] Tailwind only.

## Stop & report
This concludes **Phase 4**. Await "proceed" before Step 5.1.
