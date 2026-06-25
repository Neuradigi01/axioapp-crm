# Step 6 — Backfill DAL (conversations, custom_fields, email)

**Goal:** Create `data_access.py` in three core modules. Move all SQL/ORM out of `service.py`. Behaviour unchanged.
**Status:** Pending
**Depends on:** Step 5.
**Effort:** ~0.75 days (conversations is query-heavy).

---

## Scope

In-scope:
- `core/conversations/data_access.py` — **NEW**
- `core/custom_fields/data_access.py` — **NEW**
- `core/email/data_access.py` — **NEW** (core email send/log, distinct from `email_sequences`)
- Corresponding `service.py` updates.

Out of scope: behaviour changes, new endpoints.

## Files to touch

~6-9 files. ~400 lines net delta.

Per-module nuance:
- **conversations** — biggest of the three. Channel-agnostic thread + message queries, assignee filter, status filter. The list endpoint already does multiple JOINs — move each as a named DAL function, don't fold into one mega-query.
- **custom_fields** — definitions + values + entity-type filter. `custom_data` JSONB writes happen inline in other modules' services; those direct JSONB writes are fine and stay where they are (they're column-level, not a "query"). Only the definition CRUD moves to DAL.
- **email** — outbound send logs + template-resolution reads.

## Plan

Same pattern as Step 4. Conversations may push the line budget — if it exceeds 400 lines, split conversations out as its own follow-up step (Step 6a) and keep custom_fields + email here.

## DB changes / migrations

None.

## Tests

Run existing pytests. Conversations has the most coverage; aim for green before moving on.

## Smoke

- **conversations:** open a WhatsApp thread → messages render; reply works.
- **custom_fields:** Settings → Custom Fields → add a field for Leads → it appears on the Lead modal.
- **email:** send a test email from any template/sequence test-send modal → log row appears.

## Self-check (10 rules)

Pure relocation. ✓ Watch the conversations size. ✓ Stop-and-report. ✓
