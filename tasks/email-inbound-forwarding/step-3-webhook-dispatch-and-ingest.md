# Step 3: Local-part prefix dispatch + forwarded-address ingest branch

**Status:** COMPLETED (2026-09-21, new `parse_recipient_kind` + `extract_forwarding_token` in mailgun/service.py; new `ingest_forwarded.handle_forwarded_address` module with SPF/DKIM spoof gate + default-assignee application + `last_inbound_at` stamp; tasks.py dispatches by prefix before the existing reply-capture path; `mailgun.inbound.unknown_prefix` audit for anything else; auto-create-contact deferred to Step 4 with `forwarded_awaiting_auto_create` audit signal; 13 tests in test_mailgun_forwarded_ingest.py; pin-test exception added for the new module (mirrors mailgun/tasks.py posture))

## Goal

Extend the shipped Mailgun webhook Celery task to dispatch by local-part prefix (`in_` vs `f-`). Add the forwarded-address ingest branch.

## Files touched

- `api/src/app/core/email/mailgun/service.py` — prefix dispatch
- `api/src/app/core/email/mailgun/tasks.py` — new ingest branch
- `api/src/app/core/email/mailgun/ingest_forwarded.py` — new module for forwarded-branch logic
- `api/tests/test_mailgun_forwarded_ingest.py`

## What this step does

- Prefix dispatch in Celery task:
  ```
  local_part = extract_local_part(recipient)
  if local_part.startswith("in_"):
      handle_reply_capture(...)
  elif local_part.startswith("f-"):
      handle_forwarded_address(...)
  else:
      audit "mailgun.inbound.unknown_prefix"; drop
  ```
- `handle_forwarded_address(...)`:
  - `endpoint, details = find_by_forwarding_token(session, token=...)`. None → audit `mailgun.inbound.forwarded_unknown_token` + drop.
  - Endpoint inactive → audit + drop.
  - `SET LOCAL app.current_org_id = <endpoint.org_id>` for RLS.
  - Parse `From:` sender.
  - Call `find_contact_by_email(session, org_id=..., email=sender)`.
  - If no match:
    - `auto_create_contact=True`: `auto_create_from_email(...)` (Step 4).
    - `auto_create_contact=False`: `contact_id = None`, `system_review_required = True`.
  - SPF/DKIM check per shipped mailgun-inbound policy: fail + contact match → `contact_id=None, spoof_suspected=True`.
  - Auto-submitted check → `auto_generated=True`, skip workflow events.
  - `_persist_inbound_email(...)` with `endpoint_id=endpoint.id, endpoint_type='forwarded_address'`, `source_provider='mailgun'`, `source_reference={"mailgun_delivery_id": ..., "forwarding_token": ..., "endpoint_id": ..., "endpoint_type": "forwarded_address"}`.
  - Conversation:
    - If `In-Reply-To`/`References` matches existing → thread.
    - Else → new conversation, `assigned_to_user_id = details.default_assignee_user_id`.
- Update `details.last_inbound_at = now()` on successful persist.

## Tests

- `test_ingest_in_underscore_prefix_routes_to_reply_capture_path`
- `test_ingest_f_dash_prefix_routes_to_forwarded_address_path`
- `test_ingest_unknown_prefix_audits_and_drops`
- `test_forwarded_ingest_uses_mailgun_recipient_not_to_header`
- `test_forwarded_ingest_creates_new_conversation_on_first_touch`
- `test_forwarded_ingest_threads_by_in_reply_to_when_present`
- `test_forwarded_ingest_assigns_to_default_assignee_when_set`
- `test_forwarded_ingest_assigns_to_unassigned_when_default_null`
- `test_forwarded_ingest_spf_fail_persists_with_spoof_flag_and_null_contact`
- `test_forwarded_ingest_auto_submitted_flags_generated_skips_workflow_events`
- `test_forwarded_ingest_updates_endpoint_last_inbound_at`
- `test_forwarded_ingest_inactive_endpoint_audits_drops`

## Verification checklist

- [ ] All 12 tests pass
- [ ] Existing mailgun-inbound reply-capture smoke tests still pass
- [ ] Pin-tests pass
- [ ] Ruff clean

## Self-check

- Rule 2: pass — RLS SET LOCAL applied.
- Rule 10: pass.
- DB efficiency: pass — one endpoint lookup + one contact lookup per message.

## Stop-and-report

Report file count, test pass. **Awaiting your "proceed" for Step 4.**
