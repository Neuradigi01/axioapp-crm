# Step 2 — Reply-To injection in `send_email` (SMTP-only)

**Status:** Pending
**Effort:** ~0.25 day
**Depends on:** Step 1 (`inbound_token`, `capture_replies_in_crm` exist).
**Blocks:** Step 7 (end-to-end smoke needs outbound with Reply-To).

## Goal

Inject `Reply-To: in_{token}@{INBOUND_EMAIL_DOMAIN}` on outbound emails ONLY when:
- The resolved backend is SMTP (`smtp_sender_id is not None`), AND
- `smtp_sender.capture_replies_in_crm is True`, AND
- `smtp_sender.inbound_token is not None`.

OAuth backends (Gmail / Microsoft) are untouched. Caller-supplied `reply_to` is REPLACED — original preserved in `Message.payload.original_reply_to`.

Add a service endpoint to toggle `capture_replies_in_crm` per sender.

## Scope

**Reply-To computation in `send_email`:**

- File: `api/src/app/core/conversations/adapters/email.py`.
- In `send_email()` (line 229 today), AFTER the sender-resolution branch that loads `smtp_sender` from `smtp_sender_id`, and BEFORE calling `_build_outbound_mime`:
  ```python
  # Reply-To injection for SMTP capture (Mailgun inbound track).
  original_reply_to = reply_to
  if smtp_sender_id is not None and smtp_sender is not None:
      if smtp_sender.capture_replies_in_crm and smtp_sender.inbound_token:
          inbound_domain = os.getenv("INBOUND_EMAIL_DOMAIN", "").strip()
          if inbound_domain:
              reply_to = f"in_{smtp_sender.inbound_token}@{inbound_domain}"
  ```
- Persist `original_reply_to` into the outbound `Message.payload` dict when it differs from the final `reply_to`.

**Capture toggle endpoint:**

- `core/email_senders/service.py` — new `set_capture_toggle(session, *, org_id, sender_id, capture: bool) -> EmailSmtpSender` (owns transaction).
- `core/email_senders/router.py` — new `PATCH /api/v1/settings/email-senders/{id}/capture-toggle` — body `{capture: bool}`, response echoes the updated sender's reply-address block.
- `core/email_senders/schemas.py` — `SenderCaptureToggle` payload schema (exposes only `capture: bool`).
- Sender-detail response gets an `inbound_reply_address` sub-object: `{token: str, address: str, capture_enabled: bool}`. Address is `f"in_{token}@{INBOUND_EMAIL_DOMAIN}"`.

## Files touched

- `api/src/app/core/conversations/adapters/email.py` — Reply-To computation.
- `api/src/app/core/email_senders/service.py` — `set_capture_toggle`.
- `api/src/app/core/email_senders/router.py` — PATCH endpoint.
- `api/src/app/core/email_senders/schemas.py` — toggle payload + reply-address sub-schema.

## Tests

- `test_reply_to_injected_when_smtp_backend_and_capture_true`
- `test_reply_to_not_injected_when_smtp_backend_and_capture_false`
- `test_reply_to_not_injected_when_oauth_gmail_backend`
- `test_reply_to_not_injected_when_oauth_microsoft_backend`
- `test_reply_to_not_injected_when_INBOUND_EMAIL_DOMAIN_unset`
- `test_reply_to_format_matches_in_underscore_token_at_domain`
- `test_reply_to_replaces_caller_supplied_reply_to`
- `test_reply_to_preserves_original_in_payload_metadata`
- `test_reply_to_uses_INBOUND_EMAIL_DOMAIN_env_not_MAILGUN_DOMAIN`
- `test_capture_toggle_endpoint_updates_sender`
- `test_capture_toggle_endpoint_org_scoped_returns_404_cross_org`
- `test_capture_toggle_response_contains_reply_address_block`
- `test_sender_detail_response_includes_inbound_reply_address`
- `test_sender_detail_response_never_leaks_signing_key_or_api_key`

## Self-check

- [ ] `send_email` change is ~5 lines (no over-engineering — the `reply_to` param already flows through).
- [ ] Injection ONLY when SMTP + capture_true + token_present + INBOUND_EMAIL_DOMAIN_set.
- [ ] OAuth paths never touched.
- [ ] Toggle endpoint is org-scoped (404 on cross-org access, not 403).
- [ ] Response schema does not expose `smtp_password_enc` or any Mailgun secrets.
- [ ] Test names match plan's Tests section.

## Report template

```
Files changed: <list>

Manual verify (staging):
  1. Send a test email via SMTP sender to a personal address.
  2. Check headers: Reply-To should be `in_<token>@sandbox<hex>.mailgun.org` (or configured INBOUND_EMAIL_DOMAIN).
  3. Toggle capture=false via API, send again. Reply-To absent.
  4. Send via OAuth sender (Gmail). No Reply-To injection.

Tests: 14 pytest.

Self-check: all pass.

Awaiting proceed for Step 3.
```
