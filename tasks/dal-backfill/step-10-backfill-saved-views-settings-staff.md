# Step 10 — Backfill DAL (saved_views, settings, staff)

**Goal:** Create `data_access.py` in three core modules. Move all SQL/ORM out of `service.py`. Behaviour unchanged.
**Status:** Pending
**Depends on:** Step 9.

---

## Scope

In-scope:
- `core/saved_views/data_access.py` — **NEW**
- `core/settings/data_access.py` — **NEW** (the per-org settings module, includes the `org_settings` table)
- `core/staff/data_access.py` — **NEW**
- Corresponding `service.py` updates.

Out of scope: behaviour changes.

## Files to touch

~6-8 files. ~350 lines net delta.

Per-module nuance:
- **saved_views** — view filters per entity per user. List + CRUD. Lightweight.
- **settings** — org-level settings JSONB column reads + writes. Multiple feature-specific settings tabs (Routing, Embed, Roles, Standard Field Overrides, Email Sequences, Integrations) all read from `tbl_org_settings`. Move every read and the typed-update writes.
- **staff** — staff user records + PIN-token state. Used by Staff Portal auth.

## Plan

Same pattern as Step 4.

## DB changes / migrations

None.

## Tests

Run existing pytests.

## Smoke

- **saved_views:** create a view on Leads → reload → view persists.
- **settings:** Settings → General → change a value → save → reload → persisted.
- **staff:** Staff Portal PIN login works; staff list in Settings → Staff loads.

## Self-check (10 rules)

Pure relocation. ✓ Stop-and-report. ✓
