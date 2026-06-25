# Step 5 — Backfill DAL (billing, calls, catalog)

**Goal:** Create `data_access.py` in three core modules. Move all SQL/ORM out of `service.py`. Behaviour unchanged.
**Status:** Pending
**Depends on:** Step 4.

---

## Scope

In-scope:
- `core/billing/data_access.py` — **NEW** (core billing — invoices, payments, plan-related reads; NOT pack billing)
- `core/calls/data_access.py` — **NEW**
- `core/catalog/data_access.py` — **NEW**
- Corresponding `service.py` updates.

Out of scope: behaviour changes, new endpoints.

## Files to touch

~6-8 files. ~350 lines net delta.

Per-module nuance:
- **billing** — overlaps with `subscriptions` (Step 11) at the DB layer; keep them as separate DALs. Billing reads invoices/payments; subscriptions owns plan/seat state.
- **calls** — call-recording rows + outcome rows; uses Twilio webhook payloads. Webhook handlers may directly call `db.add`; relocate those query inserts to DAL.
- **catalog** — read-heavy (product list page); pagination + filters; one composite query for stock-on-hand. Move the query as-is into a single DAL function.

## Plan

Same pattern as Step 4:
1. Inventory queries in `service.py`.
2. Create `data_access.py` with one function per op.
3. Rewrite `service.py` to call DAL; keep transactions.
4. Smoke.

## DB changes / migrations

None.

## Tests

Run existing pytests.

## Smoke

- **billing:** Settings → Billing → invoices list loads.
- **calls:** make/log a call → row recorded; outcome dropdown saves.
- **catalog:** product list page loads; search/filter applies.

## Self-check (10 rules)

Pure relocation. < 10 files / < 400 lines. ✓ Stop-and-report. ✓
