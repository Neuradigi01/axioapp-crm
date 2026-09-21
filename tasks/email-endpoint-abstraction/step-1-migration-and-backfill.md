# Step 1: Migration — create `tbl_channel_endpoints` + `tbl_email_endpoint_details` + backfill

**Status:** Pending

## Goal

Ship the two new tables with the shape the whole track sits on, and backfill one endpoint row per existing SMTP sender and per existing OAuth mailbox. Zero behavior change — nothing reads the new tables yet.

## Files touched

- `api/alembic/versions/0225_channel_endpoints.py` — new migration
- `api/src/app/core/channel_endpoints/__init__.py` — empty package marker
- `api/src/app/core/channel_endpoints/models.py` — `ChannelEndpoint` + `EmailEndpointDetails` ORM
- `api/tests/test_channel_endpoints_migration.py` — migration + backfill assertions

## What this step does

- Create `tbl_channel_endpoints` with `id, org_id, channel, endpoint_type, label, is_active, created_at, updated_at`. `TenantScoped` mixin, RLS auto-attached.
- Create `tbl_email_endpoint_details` with `endpoint_id PK+FK, forwarding_token UNIQUE NULL, reply_token UNIQUE NULL, domain_id NULL, smtp_sender_id NULL, oauth_account_id NULL, last_inbound_at NULL`.
- Add ORM classes in `models.py`.
- Backfill: `INSERT ... SELECT` for every row in `tbl_email_smtp_senders` where `inbound_token IS NOT NULL` → 1 endpoint row (type=`smtp_reply_capture`, label=`from_address`) + 1 details row (`reply_token = inbound_token`, `smtp_sender_id` FK).
- Backfill: same for every row in `tbl_email_accounts` (type=`oauth_mailbox`, `oauth_account_id` FK).
- Idempotent: `WHERE NOT EXISTS` guards on both INSERTs. Retry-safe.
- Do NOT drop `tbl_email_smtp_senders.inbound_token`. Removal is a follow-up track.

## Migration

- Revision: `0225_channel_endpoints` (≤ 32 chars).
- `upgrade()`: CREATE both tables, indexes on `(org_id, channel, endpoint_type)`, UNIQUE on `(forwarding_token)` and `(reply_token)`, INSERT backfill.
- `downgrade()`: DROP `tbl_email_endpoint_details` then `tbl_channel_endpoints`. Legacy `inbound_token` intact.

## Tests

- `test_migration_creates_tbl_channel_endpoints`
- `test_migration_creates_tbl_email_endpoint_details`
- `test_migration_backfills_smtp_senders_to_endpoints`
- `test_migration_backfills_oauth_accounts_to_endpoints`
- `test_migration_backfill_idempotent_on_retry` — apply migration twice, row counts identical
- `test_migration_down_removes_new_tables`
- `test_migration_preserves_existing_inbound_token_column`

## Verification checklist

- [ ] `run.cmd upgrade` clean up + down
- [ ] Pin-test `test_table_name_convention.py` passes (both new tables `tbl_` prefixed)
- [ ] Pin-test `test_layered_architecture_convention.py` passes
- [ ] All 7 named tests pass
- [ ] `.py` files formatted with `ruff format`

## Self-check

- Rule 2 (`org_id` + `tbl_` prefix + RLS): pass — both tables have `org_id` via `TenantScoped`, RLS auto-attached, `tbl_` prefix.
- Rule 8 (small step): pass — 4 files, ~250 lines.
- Rule 10 (no TODOs, no commented-out): pass.
- Layered: pass — this step is models + migration only.
- Reuse: pass — reuses `TenantScoped` mixin, existing FK targets.
- DB efficiency: pass — indexes on all lookup columns.

## Stop-and-report

Report files changed, migration revision ID, backfill row counts (X SMTP endpoints + Y OAuth endpoints), test results. **Awaiting your "proceed" for Step 2.**
