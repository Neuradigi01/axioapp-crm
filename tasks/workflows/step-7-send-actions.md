# Step 7 — Send actions (email / WA / SMS / FB / IG / push / Slack)

**Goal:** Register the Send action handlers — the single largest category by operator usage. Each handler resolves the recipient, renders the linked `tbl_message_templates` row, and ships via the matching channel adapter. Pre-flight compliance gates land in Step 12; this step ships the bare send paths with a TODO-free skip path for channels without transport.
**Status:** Pending
**Depends on:** Step 4 (engine + action contract). Step 6 (variable + condition evaluator). `core/templates/` (Module A) for template lookup. `core/conversations/adapters/` for the actual send.

---

## Scope

In-scope:

- `core/workflows/actions/send.py` registering seven action handlers:
  - `send.email` — resolves recipient via the configured resolver, renders the template via `core/templates/render.py`, ships via `shared.email.get_email_backend()`. Handles attachments via the `tbl_files` reference (when ready; for now, template body only).
  - `send.whatsapp` — resolves recipient phone, uses `resolve_whatsapp_adapter` from `core/conversations/adapters/whatsapp.py`, sends via the org's default WA number. Outside Meta's 24h session window the adapter returns the standard error; the engine logs + marks step_run.errored + does NOT advance (intentional — operator sees in the run-history view).
  - `send.sms` — resolves phone, calls the SMS adapter stub (Step 12 of `tasks/template-library/`); today raises `SMSNotConfigured` which the engine catches → step_run.errored. Same shape ready for the real SMS provider.
  - `send.facebook` / `send.instagram` / `send.push` — each invokes the matching channel adapter stub (Step 13 of template-library). Skipped path consistent across the three.
  - `send.slack` — posts to the org's configured Slack webhook (via a new `core/integrations/slack/` minimal client — single file, single function `post_message(webhook_url, text)`). Workflow node config carries the webhook URL OR a reference to an org-stored webhook (Settings → Integrations → Slack — out of scope here, added when first operator needs it).

- Recipient resolver registry (`core/workflows/recipients.py` — pure helper):
  - Resolvers identified by string:
    - `contact.email` / `contact.phone` — pulls from the run's contact_id row.
    - `user.email` — the workflow's owner OR a user_id supplied in node config (for "notify the deal owner" patterns).
    - `lead.owner` — looks up the lead's assigned user, returns their email/phone per `node.config.method`.
    - `custom` — node config supplies a JSONPath against the trigger payload (e.g. `trigger_payload.contact.alt_email`).
  - `resolve(recipient_kind: str, *, run, node, context) -> str | None` — returns the resolved value or None (engine then `step_run.skipped` with reason `recipient_not_found`).

- Send-action node config (validated by Step 2's graph validator + enriched by Step 15's drawer):
  - `template_id` UUID FK to `tbl_message_templates`.
  - `channel` enum (must match the template's channel).
  - `recipient` (resolver kind + resolver-specific config).
  - `category` enum (`marketing | transactional | service`) — overrides the workflow-level `is_marketing` flag. Lets a transactional Send sit inside a marketing workflow without compliance-blocking.
  - `delay_seconds` (Optional pre-send delay — distinct from Step 11's wait nodes; this is a "small natural delay" to avoid sending two messages back-to-back in the same second).
  - `track_opens` / `track_clicks` bools — email-only.

- The handler contract: returns `ActionResult(next_edge_label=None, output={'channel_message_id': str, 'rendered_subject': str | None, 'rendered_body': str}, skip_reason=None)` on success. The `output` lands on `step_run.payload` so diagnostics + run-history can show the exact send. Variable resolution emits the rendered body through the templates module's `render()` (Step 2 of template-library).

- Compliance gate placeholder — `_compliance_check(run, node)` returns `None` for now. Step 12 swaps in the real check. Keeps the action handler's signature stable.

Out of scope:

- Real compliance enforcement (Step 12).
- Open/click tracking instrumentation in email (a future deliverability step).
- SMS-DLT pre-flight (the SMS template's DLT metadata must match the org's registered status; Step 12 wires it).
- Push provider config (Firebase / OneSignal / APNS — Step 13 of template-library only stubbed).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/workflows/actions/send.py` | **NEW** |
| `API/src/app/core/workflows/actions/__init__.py` | edit — side-effect import send.py |
| `API/src/app/core/workflows/recipients.py` | **NEW** |
| `API/src/app/core/integrations/slack/__init__.py` | **NEW** |
| `API/src/app/core/integrations/slack/client.py` | **NEW** — `post_message(webhook_url, text)` |
| `API/tests/workflows/test_send_actions.py` | **NEW** |
| `API/tests/workflows/test_recipients.py` | **NEW** |

**~7 files. ~500 lines.**

## Plan

1. Recipient resolver registry first — pure helper.
2. Slack minimal client — single async function over `httpx`.
3. Send handlers — one per channel; each maps `try/except channel_adapter_error` to `ActionResult(skip_reason='channel_error', output={'error': str})`.
4. Action registry side-effect import.
5. Tests: mock the channel adapters + assert each handler's send path resolves the right recipient + persists the channel_message_id.

## DB changes / migrations

None.

## Tests

10 pytest cases:

- `send.email` happy: resolves contact email, renders body with `{{contact.first_name}}` from context, calls backend.send, returns `channel_message_id`.
- `send.email` skips when contact has no email — `skip_reason='recipient_not_found'`.
- `send.whatsapp` happy via mocked adapter.
- `send.whatsapp` outside 24h window: adapter raises → step_run.errored.
- `send.sms` always errored today (provider not wired).
- `send.facebook` / `send.instagram` / `send.push` errored consistently (transport stubs).
- `send.slack` posts to the configured webhook URL.
- Recipient resolver `contact.email` looks up via `contact_id`.
- Recipient resolver `user.email` resolves the workflow owner (or node-config user_id).
- Recipient resolver `custom` walks the JSONPath in trigger_payload.

## Smoke

```
1. Workflow: trigger(lead.created) → send.email with template_id pointing at a published email template ("Welcome").
2. Activate. publish lead.created with {contact_id: ..., contact: {first_name: 'Asha', email: 'asha@example.com'}}.
3. Run completes; step_run for send.email has channel_message_id (or null + send-confirmation in test stub).
4. Recipient inbox receives "Welcome Asha".
5. Re-run with same workflow but template channel = WhatsApp → send.whatsapp fires.
```

## Risks

- Recipient resolver "custom" with arbitrary JSONPath: limit traversal depth to 10 + max-string-length 1000 to prevent runaway lookups against pathological payloads.
- Slack webhook URL stored in node config = secret-in-plaintext-in-DB. Mitigation: pull it from the org's `tbl_integrations.slack_webhook` row when present, encrypted via the existing crypto helpers; node config only carries a flag `use_org_default` (preferred) or the raw URL (deprecated path; flagged for replacement).
- Idempotency: a Celery retry could fire the same send twice. Mitigation: store the action's `step_run_id` as `Idempotency-Key` on the outbound HTTP call for channels that support it (Slack ignores; Meta accepts).

## Self-check (10 rules)

`core/workflows/actions/` + tiny `core/integrations/slack/`. ✓ org_id-scoped via the engine's RLS context. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions enforced upstream. pack.yaml untouched. ✓ 7 files / ~500 lines. Stop-report. ✓ No TODOs (compliance gate is a stub function explicitly extended in Step 12, not a TODO comment). ✓.

## Stop & report

```
Step 7 — Send actions
Files: 7
Verify: each send.* handler routes to the right channel adapter; recipient resolvers work; failures land on step_run.errored cleanly; Slack post lands.
Tests: 10 pytest cases.
Awaiting "proceed".
```
