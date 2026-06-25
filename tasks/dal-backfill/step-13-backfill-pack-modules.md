# Step 13 — Backfill DAL (packs/custom_orders, packs/field_ops)

**Goal:** Create `data_access.py` in the two furniture-pack modules that need it. Move all SQL/ORM out of `service.py`. Behaviour unchanged.
**Status:** Pending
**Depends on:** Step 12. (Inventory's router violation was already fixed in Step 1; inventory still needs a DAL backfill — included here as a third slot.)

---

## Scope

In-scope:
- `packs/furniture/modules/custom_orders/data_access.py` — **NEW**
- `packs/furniture/modules/field_ops/data_access.py` — **NEW**
- `packs/furniture/modules/inventory/data_access.py` — **NEW** (router was fixed in Step 1; this completes the layering by moving inventory's `service.py` queries into a DAL)
- Corresponding `service.py` updates.

Out of scope:
- Empty pack stubs (`marketplace`, `qr_marketing`, `virtual_staging`) — built in their assigned phases per the master plan; in-spec from day one.
- The incomplete `packs/furniture/modules/billing` — currently a router-only PDF generation shell; completing it is in a future Phase 4 step, not this track.

## Files to touch

~6-8 files. ~350 lines net delta.

Per-module nuance:
- **custom_orders** — custom order CRUD + status transitions. Linked to contacts and catalog items.
- **field_ops** — delivery / installation visit records; linked to staff assignments.
- **inventory** — product CRUD + stock-on-hand + alerts. Already has the transaction moved to service (Step 1); this step moves the underlying `db.add / db.query` calls into DAL functions.

**Important — `core/` never imports `packs/`.** This step touches pack modules only; the new pack DAL files don't get imported by any `core/` module.

## Plan

Same pattern as Step 4.

## DB changes / migrations

None.

## Tests

Run existing pytests.

## Smoke

- **custom_orders:** `/user/custom-orders` list loads; create one.
- **field_ops:** field-ops calendar loads; assign a delivery.
- **inventory:** inventory list loads; create a product (this is the same flow tested in Step 1 — verify still works after DAL split).

## Self-check (10 rules)

`core/` never imports `packs/`. ✓ Pure relocation. ✓ Stop-and-report. ✓
