# Step 5: Send cascade integration — refactor `send_email()` to consult `resolve_send_envelope()`

**Status:** COMPLETED 2026-09-21.

Step 5a landed the additive pieces: Mailgun API client `send_mime()` + `MailgunSendResult` parser · new `conversations/adapters/email_platform_from.py` helper with `PlatformEnvelope`/`build_platform_envelope`/`resolve_or_create_platform_reply_token`/`already_notified_first_platform_from` · 2 new test files covering send_mime multipart + platform-from helper.

Step 5b landed the refactor: `send_email` XOR guard relaxed to "at most one" (both-None → cascade, both-supplied → 400) · `resolve_send_envelope` wired inline · dispatch branches added for `own_domain` (raw MIME → `MailgunApiClient.send_mime(dispatch_domain)`) and `platform_from` (mint or reuse `platform_reply_capture` endpoint · compose `org-<uuid>@platform` from + `r-<token>@inbound` reply-to · Mailgun send · fire owner-notification once per org via `_notify_first_platform_from_send`) · `SendNotConfiguredError` → 400 with "connect a mailbox or claim a domain" copy · 11 cascade tests in `test_send_email_cascade.py` covering all four envelope kinds, first-use notification idempotency (endpoint-created gate), demoted-domain skip, both-supplied guard, and the fail-through error path.

Pin-test exceptions added for the new helper file (`core/conversations/adapters/email_platform_from.py` — token-collision retry uses `session.flush + rollback` like `channel_endpoints/data_access.create_smtp_reply_capture`).

## Goal

The primary outbound path routes through the new cascade. Fallback to platform-from is live. Existing callers work unchanged; new no-configured-sender orgs get the platform-from envelope.

## Files touched

- `api/src/app/core/conversations/adapters/email.py` — refactor `send_email()`
- `api/src/app/core/conversations/adapters/email_platform_from.py` — new helper for platform envelope construction
- `api/tests/test_send_email_cascade.py`

## What this step does

- Existing `send_email()` short-circuits when `smtp_sender_id` or `oauth_account_id` is caller-supplied. Refactor:
  ```
  envelope = resolve_send_envelope(db, org_id=org_id, caller_supplied_sender_id=smtp_sender_id or oauth_account_id)
  ```
- Envelope types drive dispatch:
  - `smtp_sender` → existing SMTP path
  - `oauth_account` → existing OAuth path (Gmail/Microsoft)
  - `own_domain` → NEW — Mailgun send API via `MailgunApiClient.send_message(domain=envelope.domain, from_=envelope.from_address, ...)`
  - `platform_from` → Mailgun send with `EMAIL_PLATFORM_SENDING_DOMAIN` domain, from `org-<uuid>@mail.karmcrm.com`, `Reply-To = r-<reply_token>@reply.karmcrm.com`
- Platform-from Reply-To token: use the org's default `smtp_reply_capture` endpoint's `reply_token` if one exists; otherwise generate a placeholder org-wide endpoint of type `platform_reply_capture` (new endpoint_type) at first-use.
- First-use platform-from notification: idempotent in-app notification `email.first_platform_from_send` with `UNIQUE(org_id, notification_key)`.
- Reply-To injection from mailgun-inbound track stays applied for SMTP sender path.

## Tests

- `test_send_cascade_caller_supplied_smtp_short_circuits`
- `test_send_cascade_caller_supplied_oauth_short_circuits`
- `test_send_cascade_falls_to_own_domain_when_no_caller_supplied`
- `test_send_cascade_falls_to_platform_from_when_no_own_domain`
- `test_send_cascade_platform_from_uses_org_uuid_local_part`
- `test_send_cascade_platform_from_reply_to_uses_r_token`
- `test_send_cascade_platform_from_creates_endpoint_row_on_first_use`
- `test_send_cascade_first_platform_from_notification_idempotent`
- `test_send_cascade_skips_demoted_own_domain`
- `test_send_cascade_raises_send_not_configured_when_all_paths_miss`

## Verification checklist

- [ ] All 10 tests pass
- [ ] Existing send-email smoke passes unchanged
- [ ] Ruff clean

## Self-check

- Rule 10: pass.
- Layered: pass.
- Reuse: pass — reuses `resolve_send_envelope` from Step 3.
- DB efficiency: pass — one envelope resolve per send call.

## Stop-and-report

Report file count, test pass, live smoke of a send via platform-from. **Awaiting your "proceed" for Step 6.**
