# Phase 4 — Furniture Pack & First Modules

**Goal:** Switch on the furniture vertical. Build the pack manifest infrastructure, apply the furniture pack to the demo org, then layer in the first three furniture modules — Inventory & Warehouse, Custom Orders, Field Operations — and Billing/POS with GST. This is where Layer 2 (`app/packs/furniture/`) starts producing real features.

**Phase completion criteria:** Furniture-specific CRM is fully functional for sales/operations: walk-ins → leads → appointments → custom orders / inventory → invoices. The pack manifest is the source of truth (no hardcoded furniture defaults anywhere in core).

## Steps

| # | Title | Status |
|---|-------|--------|
| 4.1 | [Pack manifest infrastructure](step-4.1-pack-manifest.md) | Pending |
| 4.2 | [Apply furniture pack to demo org](step-4.2-apply-pack.md) | Pending |
| 4.3 | [Inventory: backend (data)](step-4.3-inventory-data.md) | Pending |
| 4.4 | [Inventory: backend (registry)](step-4.4-inventory-registry.md) | Pending |
| 4.5 | [Inventory: Products tab](step-4.5-inventory-products.md) | Pending |
| 4.6 | [Inventory: Stock Alerts tab](step-4.6-inventory-alerts.md) | Pending |
| 4.7 | [Inventory: Add Product modal](step-4.7-inventory-add-product.md) | Pending |
| 4.8 | [Custom Orders: backend](step-4.8-custom-orders-backend.md) | Pending |
| 4.9 | [Custom Orders: frontend](step-4.9-custom-orders-frontend.md) | Pending |
| 4.10 | [Field Operations](step-4.10-field-ops.md) | Pending |
| 4.11 | [Billing/POS: backend](step-4.11-billing-backend.md) | Pending |
| 4.12 | [Billing/POS: frontend](step-4.12-billing-frontend.md) | Pending |

## Dependencies

- All steps depend on Phase 3 complete.
- 4.2 depends on 4.1 + the entire core (custom fields, pipelines, roles, etc.).
- 4.4 depends on 4.3 + Step 1.8 (module registry).
- 4.5–4.7 depend on 4.4.
- 4.8 depends on 2.9 (pipeline engine), 2.4 (contacts), 4.3 (inventory items).
- 4.9 depends on 4.8 + 2.10 (pipeline frontend) + 2.3 (dynamic form).
- 4.10 depends on 2.13 (appointments) + 3.4 (staff).
- 4.11 depends on core billing engine (created when this step starts; first invoice tables here) + org tax settings.
- 4.12 depends on 4.11.
