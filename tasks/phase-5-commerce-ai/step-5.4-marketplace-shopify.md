# Step 5.4 — Marketplace — Shopify adapter

**Goal:** Shopify Admin API adapter. Same operations.
**Phase:** 5
**Depends on:** 5.1
**Status:** Pending

## Scope
**In-scope:**
- `adapters/shopify.py` implementing `MarketplaceAdapter`.
- Custom-app or partner-app OAuth (DEFAULT: custom app — simpler since we only target the merchant's own store).
- Uses GraphQL Admin API where possible.
- Endpoints used: `orders` (fetch), `inventoryLevels` (push), `fulfillmentCreate` (tracking).

## Files to touch
- `api/app/packs/furniture/modules/marketplace/adapters/shopify.py` (created)
- `api/app/shared/config.py` (modified — Shopify settings)

## Plan
1. Connection holds `shop_domain` + `admin_access_token`.
2. fetch_orders via GraphQL paginated.
3. push_inventory updates `inventoryLevel.set`.
4. push_tracking via `fulfillmentCreate`.

## Tests to add
- `tests/test_shopify_adapter.py`

## Verification checklist
**Backend:**
- pytest green.
- with dev store, sync persists orders.

## Self-check (10 rules)
- [ ] Adapter pure.

## Stop & report
Await "proceed" before Step 5.5.
