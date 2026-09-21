# Step 3: Refactor — mailgun webhook consumes `find_by_reply_token()` from new DAL

**Status:** Pending

## Goal

Point the shipped mailgun-inbound Celery task at the new endpoints DAL. Behavior byte-identical — same audit events, same drop reasons, same persisted state. Golden byte-identical DB assertion enforces it.

## Files touched

- `api/src/app/core/email/mailgun/service.py` — `_resolve_reply_capture_sender()` refactored to use new DAL
- `api/src/app/core/email/mailgun/tasks.py` — task payload extended with `endpoint_id` alongside legacy `smtp_sender_id`
- `api/tests/test_mailgun_ingest_byte_identical.py` — golden test

## What this step does

- Existing `_resolve_reply_capture_sender()` calls `email_senders.data_access.find_by_inbound_token()`. Replace with `channel_endpoints.data_access.find_by_reply_token()` — the tuple returned still gives us the SMTP sender via `details.smtp_sender_id`.
- Extend Celery task payload dict with `endpoint_id` (the resolved endpoint's UUID). Kept alongside `smtp_sender_id` for the transition — Track 1 does not remove the legacy field.
- Feature flag `EMAIL_ENDPOINTS_REFACTOR_ENABLED` (default `true` in config, but flip-off restores old path):
  - `true` → new DAL
  - `false` → old DAL, identical behavior to pre-refactor
- Golden byte-identical test:
  - Same fixture Mailgun payload (real one from mailgun-inbound smoke).
  - Run through the pre-refactor code path (flag=false). Capture DB state (all rows in `tbl_messages`, `tbl_conversations`, `tbl_channel_endpoints`, `tbl_email_endpoint_details`, audit events).
  - Run identical payload through post-refactor (flag=true). Capture state.
  - Assert byte-identical dumps except for auto-timestamps and UUIDs.

## Tests

- `test_mailgun_webhook_ingest_byte_identical_before_after_refactor`
- `test_mailgun_ingest_populates_endpoint_id_in_message_payload`
- `test_mailgun_ingest_fallback_flag_disabled_uses_legacy_dal`
- `test_mailgun_ingest_unknown_reply_token_audits_and_drops`

## Verification checklist

- [ ] Golden byte-identical assertion passes
- [ ] Legacy path still works with flag=false
- [ ] Pin-tests pass
- [ ] Existing mailgun-inbound smoke tests still pass unchanged
- [ ] Ruff clean

## Self-check

- Rule 10 (no TODOs): pass.
- Reuse: pass — reuses Track 1's DAL from Step 2.
- Rule 2 (org isolation): pass — `find_by_reply_token()` scopes by org via endpoint row.
- Layered: pass — service calls DAL, not vice versa.

## Stop-and-report

Report files changed, byte-identical assertion output, test results. **Awaiting your "proceed" for Step 4.**
