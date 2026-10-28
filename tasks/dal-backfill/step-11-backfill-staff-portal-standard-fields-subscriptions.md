# Step 11 — Backfill DAL (staff_portal, standard_fields, subscriptions)

**Goal:** Create `data_access.py` in three core modules. Move all SQL/ORM out of `service.py`. Behaviour unchanged.
**Status:** COMPLTED
**Depends on:** Step 10.

---

## Scope

In-scope:
- `core/staff_portal/data_access.py` — **NEW**
- `core/standard_fields/data_access.py` — **NEW**
- `core/subscriptions/data_access.py` — **NEW**
- Corresponding `service.py` updates.

Out of scope: behaviour changes.

## Files to touch

~6-8 files. ~350 lines net delta.

Per-module nuance:
- **staff_portal** — PIN session token issuance + validation queries. Separate from `staff` module (which is the staff user records); staff_portal owns the short-lived session tokens for the tablet PIN UI.
- **standard_fields** — field-override CRUD + the `/standard-fields/<entity>/render` merge endpoint's lookups. The merge logic itself stays in service (it's business logic). Only the override-record queries move.
- **subscriptions** — subscription record + plan-change + seat-management queries. Includes `usage_service` queries (counts towards entitlements). Subscriptions is paired with billing (Step 5) — keep DAL boundaries clean: billing owns invoices/payments, subscriptions owns plan/seats/trial state.

## Plan

Same pattern as Step 4.

## DB changes / migrations

None.

## Tests

Run existing pytests.

## Smoke

- **staff_portal:** PIN tablet login → session token issued → protected endpoint works.
- **standard_fields:** Settings → Standard Fields → toggle a field → reload → persisted; merge endpoint reflects override.
- **subscriptions:** Settings → Billing → current plan + seat count load correctly.

## Self-check (10 rules)

Pure relocation. ✓ Stop-and-report. ✓
