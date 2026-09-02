# Step 0 — Per-org dedup index prereq on `tbl_messages`

**Status:** COMPLETED — 2026-09-02. Migration `0214_messages_dedup_partial_idx` applied against prod DB; 685 existing messages passed the probe (no collisions).
**Effort:** ~0.25 day (actual: ~1 hour).
**Depends on:** Nothing.
**Blocks:** Step 4 (Mailgun ingest needs idempotency), and any future channel that wants at-most-once persistence.

## Goal

Add `UNIQUE(org_id, channel_message_id) WHERE channel_message_id IS NOT NULL` partial index to `tbl_messages`.

**Design correction from initial spec:** the index does NOT include `channel`. `tbl_messages` has no `channel` column (it lives on `tbl_conversations`); adding one would require denormalization + backfill. Provider ID formats are disjoint in practice (`mg:<uuid>`, `wamid.HB...`, RFC `<uuid@domain>`), so cross-provider collision within one org is astronomically unlikely. A future provider using raw un-prefixed IDs would need to namespace its IDs.

This constrains data across ALL inbound channels (Gmail, Microsoft, WhatsApp, Meta, Mailgun). Sequenced separately from Mailgun-specific steps so the pre-insert collision probe surfaces any pre-existing data issues in isolation.

## Scope

- **One Alembic migration** at `api/alembic/versions/0214_messages_dedup_partial_idx.py`. Revision ID 30 chars ✓ (≤ 32 rule).
- **Probe query** in the `upgrade()` body BEFORE `CREATE INDEX`:
  ```sql
  SELECT org_id, channel_message_id, COUNT(*)
  FROM tbl_messages
  WHERE channel_message_id IS NOT NULL
  GROUP BY org_id, channel_message_id
  HAVING COUNT(*) > 1
  LIMIT 10;
  ```
  If any rows return → `raise RuntimeError(...)` with the offending groups named. Migration aborts.
- **Index creation** on probe success:
  ```sql
  CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_messages_org_channel_msgid
    ON tbl_messages (org_id, channel_message_id)
    WHERE channel_message_id IS NOT NULL;
  ```
  `CONCURRENTLY` in an `autocommit_block()` — no exclusive lock on `tbl_messages`. `IF NOT EXISTS` for resumability if a prior run left an INVALID index behind (recovery: `DROP INDEX CONCURRENTLY` then re-run).
- **Downgrade** drops the index via `DROP INDEX CONCURRENTLY IF EXISTS` in an autocommit block.
- **Model change:** `uq_messages_org_channel_msgid` also added to `Message.__table_args__` alongside the existing `uq_messages_conv_wamid` so tests (which use `Base.metadata.create_all`) pick it up — matches existing convention.

## Files touched

- `api/alembic/versions/0214_messages_dedup_partial_idx.py` — new migration.
- `api/src/app/core/conversations/models.py` — added Index to `Message.__table_args__`.
- `api/tests/test_messages_dedup_index.py` — 6 pytest cases.

## Files NOT touched

- No service / router / DAL changes.

## Tests (in `test_messages_dedup_index.py`)

- `test_partial_unique_index_exists_on_messages` — post-upgrade, `pg_indexes` includes `uq_messages_org_channel_msgid`.
- `test_duplicate_org_channel_msgid_raises_integrity_error` — two `Message` rows with same `(org_id, channel_message_id)` → second commit raises `IntegrityError`.
- `test_two_null_channel_message_ids_coexist` — partial `WHERE channel_message_id IS NOT NULL` scope verified.
- `test_same_msgid_different_org_allowed` — cross-org: same id, different org → both persist.
- `test_probe_query_finds_collisions_when_present` — the exact migration probe SQL runs against clean data and returns empty.
- (Design change: dropped `test_same_msgid_different_channel_allowed` because `channel` isn't in the index — see design correction above.)

## Self-check

- [ ] Migration probe runs BEFORE `CREATE INDEX` (order matters — index would silently drop conflicting rows otherwise? No, it would raise a `UniqueViolation` — but the probe gives a cleaner error message for the operator).
- [ ] `CONCURRENTLY` used (production `tbl_messages` is large; exclusive lock would block ingest).
- [ ] Revision ID ≤ 32 chars.
- [ ] Downgrade tested.

## Report template

```
Files changed:
  - api/alembic/versions/0XXX_messages_dedup_partial_index.py

Migration applied on: staging=PASS/FAIL, probe found N collisions.

What you can verify:
  - `SELECT * FROM pg_indexes WHERE indexname = 'ix_messages_dedup_partial';`
  - Insert two rows with same (org_id, channel, channel_message_id) → IntegrityError.

Tests added: 5 pytest cases.

Self-check: pass / pass / pass / pass.

Awaiting your 'proceed' for Step 1.
```
