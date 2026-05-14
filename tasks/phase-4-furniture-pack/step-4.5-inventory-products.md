# Step 4.5 — Inventory & Warehouse — frontend (Products tab)

**Goal:** Inventory page with Products tab matching the screenshot — card grid + list toggle, category and warehouse filters, stock badges (In Stock / Low Stock / Out / Best Seller).
**Phase:** 4
**Depends on:** 4.4
**Status:** COMPLETED

## Scope
**In-scope:**
- `app/src/app/features/user/packs/furniture/inventory/`:
  - `inventory-api.service.ts`
  - `inventory.page.ts/.html` — tab host (Products + Stock Alerts placeholder until 4.6).
  - `tabs/products.component.ts/.html` — grid/list toggle, filters, badges.
  - `product-card.component.ts/.html`
- Tailwind only.

## Files to touch
- `app/src/app/features/user/packs/furniture/inventory/*` (created)
- `app/src/app/app.routes.ts` (modified)

## Plan
1. API service.
2. Page: signals for view mode (grid/list), selected category, selected warehouse, search.
3. Stock badges:
   - Out: `qty_on_hand <= 0`
   - Low: `qty_on_hand <= reorder_level`
   - Best Seller: `is_best_seller=true`
   - In Stock: otherwise.
4. Card thumbnail uses default placeholder when no image (images stored under `/storage/{org}/inventory/{item}` — not yet uploaded; placeholder is fine for now).
5. Pagination cursor-based.

## Verification checklist
**Frontend:**
- visit `/inventory` → Products tab → grid renders with seeded items (or empty if no items yet).
- toggle list view → table.
- filter by warehouse → list narrows.

## Self-check (10 rules)
- [ ] Pack frontend lives under `app/packs/furniture/`; not in `core/`.
- [ ] Tailwind only.

## Stop & report
Await "proceed" before Step 4.6.
