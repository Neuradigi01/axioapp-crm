# Step 6.5 — Marketplace — frontend (Orders + Channels tabs)

**Goal:** Orders page with multi-channel orders (Store/Amazon/Flipkart/Shopify). Channels tab showing connection status, sync settings (auto-sync, sync inventory, auto-update tracking).
**Phase:** 6 — Furniture Pack Features
**Depends on:** 5.1, 5.2, 5.3, 5.4
**Status:** Pending

## Scope
**In-scope:**
- Fill in the marketplace shell from 5.1:
  - Orders tab: unified table — channel badge, order id, customer, totals, status, fulfilment.
  - Channels tab: 4 cards (Store/Amazon/Flipkart/Shopify). Each shows status, last_sync_at, settings toggles (auto-sync, sync_inventory, auto_update_tracking), Connect/Disconnect buttons.
- Connect modal per channel (channel-specific creds form).
- Tailwind only.

## Files to touch
- `app/src/app/features/user/packs/furniture/marketplace/orders.component.ts/.html` (created)
- `app/src/app/features/user/packs/furniture/marketplace/channels.component.ts/.html` (created)
- `app/src/app/features/user/packs/furniture/marketplace/connect-amazon.modal.ts/.html` (created)
- `app/src/app/features/user/packs/furniture/marketplace/connect-flipkart.modal.ts/.html` (created)
- `app/src/app/features/user/packs/furniture/marketplace/connect-shopify.modal.ts/.html` (created)

## Plan
1. Channels tab shows fixed 4 cards (driven by adapter registry endpoint `/marketplace/adapters` if added; else hardcoded list of 4 since these are the supported set in this build).
2. Orders tab calls `/marketplace/orders` + Store invoices endpoint (4.11) and merges.
3. Each connect modal posts creds; fields per channel.
4. Sync settings persist to `MarketplaceConnection.sync_settings`.

## Verification checklist
**Frontend:**
- visit `/marketplace` → tabs.
- connect Amazon (sandbox) → status flips to connected.
- run manual sync → orders appear in Orders tab.

## Self-check (10 rules)
- [ ] Tailwind only.

## Stop & report
Await "proceed" before Step 5.6.
