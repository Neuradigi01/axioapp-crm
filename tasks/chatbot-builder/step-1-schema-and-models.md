# Step 1 — Schema + models + migration

**Goal:** Land the `core/chatbots/` module skeleton and every table the rest of the track will read/write, so downstream steps compose against a stable schema.
**Depends on:** none
**Status:** Pending

## Scope

**In-scope**
- New backend package `API/src/app/core/chatbots/` with `__init__.py`, `models.py`, `enums.py`.
- Five new tables: `tbl_chatbots`, `tbl_chatbot_runs`, `tbl_chatbot_step_runs`, `tbl_chatbot_meters`, `tbl_chatbot_pending_replies`.
- Two column additions on existing tables: `tbl_messages.chatbot_run_id` (nullable FK), `tbl_contacts.is_placeholder` (bool default false).
- Alembic migration up + down; RLS policies on all five new tables.
- Foreign keys with cascade behaviour defined per Case list in the README.

**Out of scope**
- Service, DAL, router, engine, node handlers — all in later steps.
- Standard-fields `bot_writable` flag — Step 2.
- Frontend — Steps 12+.

## Files to touch

- `API/src/app/core/chatbots/__init__.py` (created)
- `API/src/app/core/chatbots/models.py` (created)
- `API/src/app/core/chatbots/enums.py` (created)
- `API/alembic/versions/0186_chatbots_init.py` (created — keep revision id ≤ 32 chars per memory `feedback_alembic_revision_id_length.md`)
- `API/src/app/core/conversations/models.py` (modified — add `chatbot_run_id` FK on Message)
- `API/src/app/core/contacts/models.py` (modified — add `is_placeholder` on Contact)

## Plan

1. Create the package folder + `__init__.py` importing the models for Alembic autogen.
2. `enums.py` — `ChatbotStatus (draft/live/paused/archived)`, `ChatbotRunStatus (running/parked/completed/canceled/errored)`, `ChatbotStepStatus (pending/running/completed/skipped/errored)`, `TriggerMode (any/keyword/regex)`, `TriggerChannel (any/whatsapp/email)`.
3. `models.py` — five ORM tables per Decision §1, all with `org_id UUID FK tbl_organizations` and the layered convention:
   - `tbl_chatbots (id, org_id, name, description, status, category, priority, trigger_config JSONB, graph JSONB, version_number, created_by, created_at, updated_at, archived_at)` + index on `(org_id, status)` for trigger matching hot path.
   - `tbl_chatbot_runs (id, org_id, chatbot_id, conversation_id, contact_id, lead_id, status, context JSONB, current_step_id, started_at, completed_at, canceled_reason, is_test)` + composite index `(org_id, chatbot_id, conversation_id, status)`.
   - `tbl_chatbot_step_runs (id, org_id, run_id, node_id, node_type, status, input JSONB, output JSONB, error TEXT, started_at, completed_at)` + index on `(run_id, started_at)`.
   - `tbl_chatbot_meters (id, org_id, bot_id, conversation_id, count INT DEFAULT 0, window_start TIMESTAMP, UNIQUE(org_id, bot_id, conversation_id))` — per-conversation cap; org-cap uses a separate row with `bot_id=NULL, conversation_id=NULL`.
   - `tbl_chatbot_pending_replies (id, org_id, run_id, node_id, button_id, contact_id, nonce, expires_at, consumed_at NULL, created_at)` — signed-email-URL nonce store for Step 11.
4. Add `chatbot_run_id UUID FK tbl_chatbot_runs ON DELETE SET NULL` on `Message`; add `is_placeholder BOOLEAN DEFAULT FALSE NOT NULL` on `Contact`.
5. Alembic migration:
   - Create all five tables + FKs + indexes.
   - Add columns on `tbl_messages` + `tbl_contacts`.
   - Enable RLS on the five new tables; policy `org_id = current_setting('app.current_org_id')::uuid`.
   - `downgrade()` drops in reverse order.

## DB changes / migrations

New tables + one FK column + one boolean column. Revision id `0186_chatbots_init` (28 chars — fits). Verify with `run.cmd upgrade` and `run.cmd downgrade -1` locally before reporting.

## Tests to add

Location: `API/tests/core/chatbots/test_schema.py` (created)

- `test_tbl_chatbots_has_org_id_and_rls` — asserts the RLS policy exists via `pg_policies` query.
- `test_all_new_tables_prefixed_tbl_` — satisfies the CI pin-test `test_table_name_convention.py`.
- `test_message_chatbot_run_id_nullable_and_set_null_on_delete` — cascade behavior.
- `test_contact_is_placeholder_defaults_false` — column default.

## Verification checklist

**Backend**
- [ ] `run.cmd upgrade` applies migration 0186 without error.
- [ ] `run.cmd downgrade -1` reverses cleanly.
- [ ] `psql \d tbl_chatbots` shows expected columns + FKs + indexes.
- [ ] `SELECT * FROM pg_policies WHERE tablename LIKE 'tbl_chatbot%'` returns 5 rows (one per table).

**Frontend** — N/A this step.

**Code review**
- [ ] Every new table has `org_id UUID FK tbl_organizations` (rule #2).
- [ ] Every table name has `tbl_` prefix (rule #2, memory `feedback_backend_layered_architecture`).
- [ ] Only ORM defined in `models.py` — no service logic (Router→Service→DAL rule).
- [ ] No imports from `packs/` (rule #1).
- [ ] Revision id ≤ 32 chars (memory `feedback_alembic_revision_id_length.md`).

## Self-check (10 rules)

- [ ] `core` did not import `packs`
- [ ] `org_id` present on all new tables + RLS enabled
- [ ] Layered custom-fields model unchanged (Case 6 handled at service layer, not schema)
- [ ] Dynamic-form contract unchanged (N/A this step)
- [ ] Sidebar registry not touched yet (Step 3)
- [ ] Permission registry not touched yet (Step 3)
- [ ] Pack manifest N/A
- [ ] Under 10 files, under 400 lines
- [ ] Verification runnable — migration up + down
- [ ] Zero TODOs, no commented-out code, no shortcuts

## Stop & report

Report the migration revision id, files created/modified, and the raw `CREATE TABLE` statements executed for pasting into the DB if needed. Await "proceed".
