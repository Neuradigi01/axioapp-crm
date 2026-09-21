# Step 6: `v:` variable stamping in Mailgun API client + campaign integration

**Status:** Pending

## Goal

Every Mailgun send stamps `v:org`, `v:envelope`, `v:endpoint`, `v:domain_id`, `v:campaign` so the events webhook (Step 3) can attribute. Campaign send loop consumes the gate chain.

## Files touched

- `api/src/app/core/email/mailgun/api_client.py` — extend `send_message()` with `custom_variables: dict[str, str] | None = None` param
- `api/src/app/core/conversations/adapters/email.py` — pass `v:` dict from send-envelope resolution
- `api/src/app/core/campaigns/service.py` — campaign send loop uses `send_email()` (already does; verify skip-codes handled)
- `api/tests/test_v_variable_stamping.py`

## What this step does

- API client `send_message()`:
  - Adds `data["v:{key}"] = value` to the POST form for each custom var.
  - Validates charset `[A-Za-z0-9_-]` per locked decision. Rejects otherwise.
  - Values coerced to string (UUIDs stringified).
- Send call site in `send_email()`:
  - After envelope + gate pass, build `custom_variables = {"org": str(org_id), "envelope": envelope_type, "endpoint": str(endpoint_id) if endpoint_id else "none", "domain_id": str(domain_id) if domain_id else "none", "campaign": str(campaign_id) if campaign_id else "none"}`.
  - Pass to `client.send_message(..., custom_variables=custom_variables)`.
- Campaign service:
  - Verify skip codes (`SKIPPED_*`) surfaced to campaign progress log.
  - Skip = counted as skipped, not failed. Campaign continues.

## Tests

- `test_client_stamps_v_prefix_variables_on_post_form`
- `test_client_rejects_v_value_with_invalid_charset`
- `test_client_stringifies_uuid_values`
- `test_send_email_stamps_org_envelope_endpoint_domain_campaign`
- `test_send_email_stamps_none_for_null_ids`
- `test_campaign_send_loop_logs_skip_code_per_recipient`
- `test_campaign_send_loop_continues_after_skip_reputation_block`

## Verification checklist

- [ ] All 7 tests pass
- [ ] Existing campaign send smoke unaffected
- [ ] Pin-tests pass
- [ ] Ruff clean

## Self-check

- Rule 2: pass — `v:` values server-set only; caller can't override.
- Rule 10: pass.

## Stop-and-report

Report file count, test pass. **Awaiting your "proceed" for Step 7.**
