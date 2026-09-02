# Step 0 — Cross-channel dedup index prereq on `tbl_messages`

**Status:** Pending
**Effort:** ~0.25 day
**Depends on:** Nothing.
**Blocks:** Step 4 (Mailgun ingest needs idempotency), and any future channel that wants at-most-once persistence.

## Goal

Add `UNIQUE(org_id, channel, channel_message_id) WHERE channel_message_id IS NOT NULL` partial index to `tbl_messages`. This is a **cross-channel prereq** — it constrains Gmail, Microsoft, WhatsApp, Meta inbound messages too, not just Mailgun.

Sequenced separately from the Mailgun-specific steps so that if the pre-insert collision probe hard-fails on existing production data, we discover it in a self-contained migration rather than tangled with a Mailgun step.

## Scope

- **One Alembic migration** at `api/alembic/versions/`. Revision ID ≤ 32 chars.
- **Probe query** in the `upgrade()` body BEFORE the `CREATE INDEX`:
  ```sql
  SELECT org_id, channel, channel_message_id, COUNT(*)
  FROM tbl_messages
  WHERE channel_message_id IS NOT NULL
  GROUP BY org_id, channel, channel_message_id
  HAVING COUNT(*) > 1
  LIMIT 10;
  ```
  If any rows return → `raise RuntimeError(f"Cross-channel dedup collisions found: {rows}")`. Migration aborts. Operator fixes data, re-runs.
- **Index creation** on probe success:
  ```sql
  CREATE UNIQUE INDEX CONCURRENTLY ix_messages_dedup_partial
    ON tbl_messages (org_id, channel, channel_message_id)
    WHERE channel_message_id IS NOT NULL;
  ```
  `CONCURRENTLY` for zero-downtime — no exclusive lock on `tbl_messages`. Must be run OUTSIDE a transaction; Alembic `op.execute()` with `autocommit_block()` context.
- **Downgrade** drops the index.

## Files touched

- `api/alembic/versions/0XXX_messages_dedup_partial_index.py` — new migration.

## Files NOT touched

- No ORM model change (partial indexes not typically declared in SQLAlchemy metadata — the migration is the source of truth).
- No service / router / DAL changes.

## Tests

- `test_step0_migration_probe_hard_fails_on_channel_message_id_collision` — insert two `tbl_messages` rows with same `(org_id, channel, channel_message_id)`, run migration, assert `RuntimeError`.
- `test_step0_migration_probe_passes_on_clean_data` — insert distinct rows, run migration, assert index exists via `pg_indexes` query.
- `test_step0_migration_partial_unique_index_created` — post-upgrade, `pg_indexes` includes `ix_messages_dedup_partial` on `tbl_messages`.
- `test_step0_migration_down_drops_index` — downgrade, assert index absent.
- `test_step0_index_ignores_null_channel_message_id` — insert two rows both with `channel_message_id=NULL` after upgrade; both succeed (partial index scope).

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
