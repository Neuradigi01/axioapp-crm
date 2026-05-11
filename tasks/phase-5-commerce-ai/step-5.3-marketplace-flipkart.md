# Step 5.3 — Marketplace — Flipkart adapter

**Goal:** Flipkart Seller API adapter. Same operations as Amazon (connect/fetch_orders/push_inventory/push_tracking).
**Phase:** 5
**Depends on:** 5.1
**Status:** Pending

## Scope
**In-scope:**
- `adapters/flipkart.py` implementing `MarketplaceAdapter`.
- Token exchange via Flipkart Seller API OAuth.
- Endpoints used: `/sellers/v3/orders`, `/sellers/skus/listings/v3/update`, `/sellers/v3/shipments/{id}/manifest`.

## Files to touch
- `api/src/app/packs/furniture/modules/marketplace/adapters/flipkart.py` (created)
- `api/src/app/shared/config.py` (modified — Flipkart settings)

## Plan
1. Implement OAuth + signed request helper.
2. fetch_orders: paginated by `fromDate`/`toDate`.
3. push_inventory: bulk SKU listings update.
4. push_tracking: shipment confirmation.

## Tests to add
- `tests/test_flipkart_adapter.py` — mocks API; happy path + error handling.

## Verification checklist
**Backend:**
- pytest green.
- with sandbox creds (or recorded VCR), sync persists orders.

## Self-check (10 rules)
- [ ] Adapter pure.

## Stop & report
Await "proceed" before Step 5.4.
