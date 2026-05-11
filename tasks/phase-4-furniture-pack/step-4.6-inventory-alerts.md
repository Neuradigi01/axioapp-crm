# Step 4.6 — Inventory & Warehouse — Stock Alerts tab

**Goal:** Stock Alerts tab with reorder priority and quick "Reorder" action.
**Phase:** 4
**Depends on:** 4.5
**Status:** Pending

## Scope
**In-scope:**
- `tabs/stock-alerts.component.ts/.html` under the Inventory page.
- Lists open alerts ordered by priority then qty_on_hand asc.
- "Reorder" action: opens a small modal to record a planned reorder; sets `alert.status='ordered'` and creates a placeholder `InventoryMovement` of type=`receipt_planned` with qty=`suggested_reorder_qty` (configurable).
- "Mark Closed" button when stock is restored.

## Files to touch
- `app/src/app/features/user/packs/furniture/inventory/tabs/stock-alerts.component.ts/.html` (created)

## Plan
1. List with severity color (red=out, amber=low).
2. Reorder modal: confirm qty, supplier (free text — supplier model out of scope for now).
3. Refresh list after action.

## Verification checklist
**Frontend:**
- with low-stock items, alerts list shows them.
- click Reorder → status `ordered`.

## Self-check (10 rules)
- [ ] No imports from `core/` *into* the pack? — opposite is allowed; pack imports core freely. Confirm pack doesn't accidentally pollute core.

## Stop & report
Await "proceed" before Step 4.7.
