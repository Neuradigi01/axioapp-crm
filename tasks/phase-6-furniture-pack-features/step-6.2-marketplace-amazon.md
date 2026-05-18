# Step 6.2 — Marketplace — Amazon adapter

**Goal:** Amazon SP-API integration. Connect/disconnect, fetch orders, basic inventory push. Test with sandbox credentials.
**Phase:** 6 — Furniture Pack Features
**Depends on:** 5.1
**Status:** Pending

## Scope
**In-scope:**
- `app/packs/furniture/modules/marketplace/adapters/amazon.py` implementing `MarketplaceAdapter`:
  - LWA token exchange + refresh.
  - SP-API call helpers (signed requests).
  - `fetch_orders(since)` using SP-API Orders.
  - `push_inventory(items)` via SP-API Listings/Feeds.
  - `push_tracking(order_id, tracking)` via SP-API Confirm Shipment feed.
- Settings: `AMAZON_LWA_CLIENT_ID`, `AMAZON_LWA_CLIENT_SECRET`, default region.
- Per-connection creds: refresh_token, marketplace_id.
- Celery task `sync_marketplace(connection_id)` — fetches new orders since last_sync_at.

## Files to touch
- `api/src/app/packs/furniture/modules/marketplace/adapters/amazon.py` (created)
- `api/src/app/packs/furniture/modules/marketplace/tasks.py` (created — Celery)
- `api/src/app/shared/config.py` (modified — Amazon settings)

## Plan
1. Implement adapter using `python-amazon-sp-api` (well-maintained) OR raw httpx — DEFAULT decision: `python-amazon-sp-api` to save time; pin version.
2. Encrypt creds at rest via the symmetric key from 5.1.
3. Celery task: opens connection, calls fetch_orders, upserts MarketplaceOrders.
4. On new order, optionally create a Lead or move into the leads pipeline (controlled by `sync_settings`).

## Tests to add
- `tests/test_amazon_adapter.py` — mocks SP-API; verifies fetch + persist.

## Verification checklist
**Backend:**
- with sandbox creds, `POST /marketplace/connections/{id}/sync` → orders persisted.
- pytest green.

## Self-check (10 rules)
- [ ] Adapter is the only place that knows Amazon API.

## Stop & report
Await "proceed" before Step 5.3.
