# Step 4.11 — Furniture: Billing / POS — backend

**Goal:** Use core billing engine (built here for the first time, kept core-generic). Furniture-specific invoice template. POS endpoint optimized for in-store quick checkout. GST calculation reads from org settings (not hardcoded).
**Phase:** 4
**Depends on:** 3.17 (settings), 3.3 (catalog), 4.3 (inventory)
**Status:** Pending

## Scope
**In-scope:**
- Core billing engine (in `app/core/billing/`, kept generic):
  - Models:
    - `Invoice` (TenantScoped): id, org_id, number (org-unique sequence), contact_id, status (draft/issued/paid/void), subtotal, tax_amount, discount_amount, total, currency, gst_number (snapshot of org gst at issue time), issued_at, paid_at, payment_method (cash/card/upi/emi/cheque/bank), notes, created_at.
    - `InvoiceLine` (TenantScoped): id, org_id, invoice_id, catalog_item_id (nullable for ad-hoc), description, qty, unit_price, line_subtotal, tax_pct, line_total.
    - `Payment` (TenantScoped): id, org_id, invoice_id, amount, method, reference, received_at.
  - Migration `0026_billing.py` + RLS + sequence per (org_id) for invoice number.
  - Service: `create_draft`, `add_line`, `issue`, `record_payment`, `void`. Tax = `org_settings.tax_rate` at issuance time.
  - Endpoints: `/invoices` CRUD + `/invoices/{id}/issue` + `/invoices/{id}/payments`.
  - Permission: `billing.read`, `billing.write`, `billing.refund`, `pos.use`, `pos.refund`.
- Furniture pack module:
  - `app/packs/furniture/modules/billing/`:
    - Invoice template (PDF generator) tuned for furniture (logo, GST line, INR formatting).
    - POS endpoint `POST /api/v1/pos/checkout` — single-call quick checkout:
      - Accepts contact phone + cart lines + payment method + discount.
      - Auto-creates contact if missing.
      - Creates invoice + lines + payment in one transaction.
      - Decrements inventory for any line with `catalog_item_id` linked to inventory.
      - Returns invoice + printable URL.
    - Module descriptor (sidebar entry "Billing & POS", layer=`pack`).

## Files to touch
- `api/src/app/core/billing/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0026_billing.py` (created)
- `api/src/app/packs/furniture/modules/billing/{__init__,router,pdf,module}.py` (created)
- `api/src/app/main.py` (modified)

## Plan
1. Core billing models + migration. Invoice number generated via Postgres sequence per org (`bigserial` per-org-table or composite trick — use a `org_invoice_seq` table with `(org_id, last_number)` row + locked update for simplicity).
2. Core service: state machine (draft → issued → paid → void).
3. Pack POS endpoint orchestrates contact lookup + invoice + payment + inventory decrement.
4. Pack PDF generator using `reportlab` or `weasyprint` (DEFAULT: weasyprint with HTML/CSS template — better for typography).
5. Permission registration; furniture pack manifest grants pos.use to relevant roles.

## Tests to add
- `tests/test_billing_lifecycle.py` — draft → issue → pay → void.
- `tests/test_pos_checkout.py` — happy path; inventory decrements; tax computed.

## Verification checklist
**Backend:**
- `POST /pos/checkout` → 201 invoice with status=`issued`, payment recorded, inventory decremented.
- `GET /invoices/{id}/pdf` → PDF download.

## Self-check (10 rules)
- [ ] Tax pulled from org settings, not hardcoded.
- [ ] Core billing has no furniture knowledge; pack provides template + POS endpoint.

## Stop & report
Await "proceed" before Step 4.12.
