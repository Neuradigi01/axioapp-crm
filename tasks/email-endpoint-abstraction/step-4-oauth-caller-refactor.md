# Step 4: Refactor — OAuth ingest records `endpoint_id` in message payload

**Status:** COMPLETED (2026-09-21) — `_persist_inbound_email` gains optional `endpoint_id` kwarg (default None, backwards-compatible); `receive_email` resolves the backing OAuth-mailbox endpoint via a module-level 300s TTL cache (N+1-safe — one DAL lookup per account per 5 min); Mailgun path unaffected (uses source_reference["endpoint_id"] pattern from Step 3); shared `EMAIL_ENDPOINTS_REFACTOR_ENABLED` flag mirrored so one env var flip reverts both OAuth and Mailgun paths.

## Goal

Extend the shipped OAuth ingest path (`receive_email` for Gmail + Microsoft) to look up its own endpoint row and stamp `endpoint_id` on persisted messages. Byte-identical output except for the new `payload.source_reference.endpoint_id` field.

## Files touched

- `api/src/app/core/conversations/adapters/email.py` — `_persist_inbound_email()` accepts optional `endpoint_id`
- `api/src/app/core/email/gmail/sync.py` — resolve endpoint via `find_active_for_org(endpoint_type='oauth_mailbox')` matching the OAuth account
- `api/src/app/core/email/microsoft/sync.py` — same
- `api/tests/test_oauth_ingest_endpoint_id_stamped.py`

## What this step does

- `_persist_inbound_email(...)` gains optional param `endpoint_id: UUID | None = None`. When passed, stamps into `message.payload["source_reference"]["endpoint_id"] = str(endpoint_id)`.
- OAuth sync (Gmail + Microsoft) resolves endpoint at receive time: `endpoints = find_active_for_org(session, org_id=org_id, endpoint_type='oauth_mailbox')`, filter to the one whose `details.oauth_account_id == this_account.id`. Cache the endpoint_id on the sync session so N mail events don't do N DAL calls.
- If no endpoint row exists (edge case for OAuth account created before Step 1 backfill), log warning + skip stamping (message still ingests). Nightly job (Step 5) auto-creates a missing endpoint for such accounts.
- Byte-identical assertion: pre-refactor persisted messages have `payload.source_reference = {"provider": "gmail", "account_id": "..."}`. Post-refactor same fields PLUS `endpoint_id`. Test asserts all other fields byte-identical.

## Tests

- `test_oauth_gmail_persist_stamps_endpoint_id`
- `test_oauth_microsoft_persist_stamps_endpoint_id`
- `test_oauth_persist_missing_endpoint_logs_warning_still_ingests`
- `test_oauth_receive_email_byte_identical_except_new_endpoint_id`
- `test_oauth_endpoint_cache_avoids_n_plus_1_dal_calls`

## Verification checklist

- [ ] Byte-identical assertion (all fields except `endpoint_id`) passes
- [ ] N+1 avoidance verified — one DAL call per sync session, not per message
- [ ] Existing OAuth sync smoke tests pass
- [ ] Ruff clean

## Self-check

- Rule 10: pass.
- DB efficiency: pass — cached endpoint per sync session.
- Reuse: pass — extends existing `_persist_inbound_email` param list.
- Layered: pass.

## Stop-and-report

Report files changed, byte-identical assertion, test results. **Awaiting your "proceed" for Step 5.**
