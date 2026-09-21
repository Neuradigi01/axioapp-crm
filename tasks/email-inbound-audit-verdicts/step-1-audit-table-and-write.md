# Step 1: Migration — `tbl_email_inbound_deliveries` + retention beat + audit write in webhook

**Status:** COMPLETED (2026-09-21) — migration `0237_email_inbound_audit` on `crm_local`; `tbl_email_inbound_deliveries` has 15 columns + 3 indexes (`received_at DESC`, partial on `mailgun_delivery_id`, composite `outcome, received_at DESC`) + CHECK on outcome enum; **documented deviation from Rule 2** — no `org_id` column (precedent: `tbl_email_inbound_dlq`); `EmailInboundDelivery` ORM in `audit_deliveries.py`; `write_audit(AuditPayload)` best-effort with per-request `async_session` + `ipaddress` sanitisation; wired into `mailgun_inbound` webhook via `asyncio.create_task(write_audit(...))` on all 3 exit paths (`signature_rejected` / `replay_rejected` / `enqueued`); daily 05:00 UTC retention beat `sweep_inbound_deliveries_daily` in new `audit_retention_task.py` module, batched at 10k rows; task in autodiscover; downgrade+re-upgrade round-trip clean.

## Goal

Append-only audit trail of every mailgun webhook receipt. Best-effort write. 90-day retention. Metadata only — no message content.

## Files touched

- `api/alembic/versions/0230_email_inbound_audit.py` — migration
- `api/src/app/core/email/mailgun/audit_deliveries.py` — DAL + write helper
- `api/src/app/core/email/mailgun/service.py` — call audit write from webhook
- `api/src/app/core/email/mailgun/tasks.py` — retention beat
- `api/src/app/celery/worker.py` — autodiscover
- `api/src/app/shared/celery_config.py` — daily beat entry
- `api/tests/test_inbound_audit_deliveries.py`

## What this step does

- Migration:
  - CREATE TABLE `tbl_email_inbound_deliveries` per README schema:
    - `id UUID PK gen_random_uuid()`
    - `mailgun_delivery_id VARCHAR(64) NULL`
    - `mailgun_message_id VARCHAR(255) NULL`
    - `received_at TIMESTAMPTZ NOT NULL DEFAULT now()`
    - `signature_status VARCHAR(16) NOT NULL`
    - `replay_status VARCHAR(16) NOT NULL`
    - `timestamp_status VARCHAR(16) NOT NULL`
    - `recipient VARCHAR(255) NULL`
    - `sender VARCHAR(255) NULL`
    - `payload_size_bytes INT NULL`
    - `attachment_count INT NULL`
    - `outcome VARCHAR(24) NOT NULL`
    - `outcome_detail JSONB NOT NULL DEFAULT '{}'::jsonb`
    - `client_ip INET NULL`
    - `user_agent VARCHAR(255) NULL`
  - **No `org_id` — system-level table.** Documented DEVIATION from rule 2 in the migration file's docstring.
  - CHECK outcome IN ('enqueued', 'signature_rejected', 'replay_rejected', 'timestamp_rejected', 'size_rejected_before_download').
  - Index `(received_at DESC)`, `(mailgun_delivery_id) WHERE mailgun_delivery_id IS NOT NULL`, `(outcome, received_at DESC)`.
- Audit helper `audit_deliveries.py`:
  - `write_audit(session, *, mailgun_delivery_id, mailgun_message_id, signature_status, replay_status, timestamp_status, recipient, sender, payload_size_bytes, attachment_count, outcome, outcome_detail, client_ip, user_agent) -> None`.
  - Best-effort: try/except; log warning + continue on failure. Don't block pipeline.
- Webhook integration in `mailgun/service.py`:
  - After signature verification (whichever branch), fire-and-forget `asyncio.create_task(write_audit(...))` so response time stays constant.
  - Response-time-constancy test asserts this.
- Retention task `sweep_inbound_deliveries_daily()`:
  - Delete rows `received_at < now() - EMAIL_INBOUND_DELIVERIES_RETAIN_DAYS (90)`.
  - Batched at 10k rows per beat run.
- Beat entry: 05:00 UTC daily.

## Tests

- `test_migration_creates_tbl_email_inbound_deliveries`
- `test_migration_no_org_id_column`
- `test_migration_check_constraint_outcome_enum`
- `test_migration_indexes_present`
- `test_audit_row_written_on_signature_valid`
- `test_audit_row_written_on_signature_invalid`
- `test_audit_row_written_on_replay_rejected`
- `test_audit_row_written_on_timestamp_stale`
- `test_audit_row_written_on_size_rejected`
- `test_audit_write_best_effort_does_not_block_pipeline_on_failure`
- `test_audit_write_response_time_constant_regardless_of_outcome`
- `test_retention_beat_deletes_rows_older_than_90_days`
- `test_retention_batched_at_10k_per_beat`

## Verification checklist

- [ ] Migration up + down clean
- [ ] All 13 tests pass
- [ ] Beat entry registered
- [ ] Task in autodiscover
- [ ] Existing mailgun-inbound smoke unaffected
- [ ] Ruff clean

## Self-check

- **Documented deviation from Rule 2** (`org_id`): system-level table. Precedent: `tbl_email_inbound_dlq` — same shape.
- Rule 8: pass — 7 files.
- Layered: pass.
- Memory `feedback_celery_task_autodiscover_list.md`: pass.

## Stop-and-report

Report migration revision, test pass, deviation from Rule 2 documented. **Awaiting your "proceed" for Step 2.**
