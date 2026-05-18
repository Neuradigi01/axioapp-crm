# Step 6.1 — Marketplace Sync — abstraction

**Goal:** `fp_marketplace_connections` and `fp_marketplace_orders` tables. Marketplace adapter interface (connect, fetch_orders, push_inventory, push_tracking). Channels page UI shell.
**Phase:** 6 — Furniture Pack Features
**Depends on:** 4.3 (inventory)
**Status:** Pending

## Scope
**In-scope:**
- Models (TenantScoped, fp_*):
  - `MarketplaceConnection`: id, org_id, channel (amazon/flipkart/shopify), display_name, credentials (encrypted JSONB), status (connected/disconnected/error), last_sync_at, sync_settings JSONB (auto_sync, sync_inventory, auto_update_tracking).
  - `MarketplaceOrder`: id, org_id, connection_id, external_order_id, status, customer JSONB, lines JSONB, totals JSONB, ordered_at, raw JSONB.
- Migration `0027_fp_marketplace.py` + RLS.
- Adapter interface `MarketplaceAdapter`:
  - `connect(creds) -> ok`
  - `fetch_orders(since) -> [RawOrder]`
  - `push_inventory(items) -> ok`
  - `push_tracking(order_id, tracking) -> ok`
- Connection registry similar to channel registry.
- Endpoints: `/marketplace/connections` CRUD, `/marketplace/connections/{id}/sync` (admin trigger), `/marketplace/orders` (paginated, filter by channel).
- Frontend shell: `app/src/app/features/user/packs/furniture/marketplace/marketplace.page.ts/.html` — tab host (Orders + Channels).

## Files to touch
- `api/src/app/packs/furniture/modules/marketplace/{__init__,models,schemas,service,router,adapters,registry,module}.py` (created)
- `api/alembic/versions/0027_fp_marketplace.py` (created)
- `app/src/app/features/user/packs/furniture/marketplace/*` (created — shell only)

## Plan
1. Models + migration; encrypt credentials column at rest (use a per-org symmetric key stored in env for now; rotate later).
2. Adapter base class + registry.
3. Endpoints with admin permissions (`marketplace.manage`).
4. Frontend shell with empty Orders + Channels tabs (filled in 5.5).

## Tests to add
- `tests/test_marketplace_models.py`

## Verification checklist
**Backend:**
- migration applies.
- `GET /marketplace/connections` → empty.

## Self-check (10 rules)
- [ ] org_id + RLS.
- [ ] Pack-only.

## Stop & report
Await "proceed" before Step 5.2.
