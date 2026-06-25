# Step 5 — Test send and sidebar registration

**Goal:** Per-channel test-send endpoint + register the new module in the core module registry (sidebar entry + permission scope + menu icon). Backend-side, this is the last step before frontend work begins.
**Status:** COMPLETED — `core/templates/test_send.py` (validator + email-via-`shared.email.get_email_backend` + WhatsApp-via-`resolve_whatsapp_adapter` + audit-row writer); two new exceptions (`TestSendNotSupported`, `InvalidRecipient`); `TestSendPayload` schema + `POST /api/v1/templates/{id}/test-send` endpoint gated on `templates.write` (404 on missing template, 400 on invalid recipient, 501 on SMS/FB/IG/push, 200 with `TemplateTestSendRead` on success). `core/templates/module.py` flipped `menu_position=None → 250` so the "Templates" sidebar entry surfaces for Owner/Admin/Employee (everyone with `templates.read`). FileText Lucide icon already in `APP/src/app.config.ts` registry (no edit needed — spec assumption). 11 pytest cases in `test_test_send.py` (deferred run). **Post-Step-7 fix (2026-06-25):** removed the explicit `registry.register(MODULE)` line at the bottom of `module.py` — `discover_modules()` already registers via `getattr(mod, "MODULE", None)`. The duplicate call was crashing the lifespan with `ValueError: module 'templates' is already registered`. Now matches the established `core/activities/module.py` pattern.
**Depends on:** Step 3 (router + perms), Step 4 (workflow). Reuses existing channel adapters at `core/conversations/adapters/`.

---

## Scope

In-scope:
- `core/templates/test_send.py`:
  - `dispatch_test_send(org_id, template_id, recipient, user_id) → TemplateTestSend`.
  - Channel-aware dispatch: WhatsApp via `core/conversations/adapters/whatsapp.py`, Email via `core/conversations/adapters/email.py`. SMS / FB / IG / push raise `TestSendNotSupported` until their adapters land in Steps 12 + 13.
  - Variable resolution uses Step-2's `resolve()` with a synthetic context: real org row + the requesting user's contact data (or explicit `sample_context` if provided in payload).
  - Inserts a row into `tbl_message_template_test_sends` (audit, includes `channel_message_id` returned by the adapter).
- `POST /api/v1/templates/{id}/test-send` endpoint:
  - Body: `{recipient: str, sample_context?: dict}`. Recipient is phone for WA/SMS, email for Email, channel-handle for FB/IG/push.
  - Permission: `templates.write` (writing implies test-send rights).
  - Recipient validation: phone format for WA/SMS, RFC-5322 lite for Email.
  - Returns the `TemplateTestSend` row.
- `core/templates/module.py`:
  - Module descriptor declaring sidebar position, icon (`file-text` Lucide), label ("Templates"), permission scope (`templates.read`), and the route slug (`/user/templates`).
  - Registers with the existing core module registry (mirrors `core/reporting/module.py` from `whatsapp-platform-upgrade` Step 20).
- `app/core/module_registry.py`: confirm the new module loads on app start; one new entry is enough (no other change).
- Sidebar icon (`file-text`) added to `APP/src/app.config.ts` Lucide registry (per the `feedback_lucide_icon_registry.md` memory).

Out of scope:
- Frontend test-send modal (Step 8).
- SMS / FB / IG / push test-send paths (return 501 here; wired in Steps 12 + 13).
- Sidebar UI rendering — Angular sidebar already iterates the registry; one new entry shows up automatically.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/templates/test_send.py` | **NEW** |
| `API/src/app/core/templates/router.py` | edit — `POST /templates/{id}/test-send` |
| `API/src/app/core/templates/schemas.py` | edit — `TestSendPayload`, `TemplateTestSendRead` |
| `API/src/app/core/templates/exceptions.py` | edit — `TestSendNotSupported`, `InvalidRecipient` |
| `API/src/app/core/templates/module.py` | **NEW** — module descriptor |
| `APP/src/app.config.ts` | edit — register `file-text` Lucide icon |
| `API/tests/templates/test_test_send.py` | **NEW** |

**~7 files. ~400 lines.**

## Plan

1. `test_send.py` — single function that switches on channel, resolves variables, calls the channel adapter's `send()`, inserts an audit row.
2. Wire endpoint into router.
3. `module.py` — registry descriptor.
4. Lucide icon: add `FileText` to the `app.config.ts` registry mapping.
5. Tests cover WA happy path, Email happy path, SMS/FB/IG/push raise 501, invalid recipient → 400, audit row written.

## DB changes / migrations

None — `tbl_message_template_test_sends` exists from Step 1.

## Tests

8 pytest cases:
- `test_dispatch_wa_test_send_happy_path` (mocked adapter).
- `test_dispatch_email_test_send_happy_path` (mocked adapter).
- `test_dispatch_sms_returns_not_supported`.
- `test_dispatch_fb_returns_not_supported`.
- `test_invalid_phone_format_rejected`.
- `test_invalid_email_format_rejected`.
- `test_audit_row_inserted_with_channel_message_id`.
- `test_test_send_works_on_draft_template` (no requirement to be published).

## Smoke

```
1. As Owner, POST /templates {channel=email, ...} → 200 draft.
2. POST /templates/{id}/test-send {recipient: "owner@example.com"} → 200; check inbox.
3. SELECT * FROM tbl_message_template_test_sends WHERE template_id=...; → one row.
4. POST /templates/{id}/test-send {recipient: "invalid"} → 400.
5. Sidebar in browser: "Templates" entry appears (route `/user/templates` 404s for now — Step 6 fills it).
```

## Risks

- Email test-send needs a connected sender mailbox (Gmail/Outlook OAuth) on the requesting user. If none, return 400 with "connect an email account in Settings → Email Accounts."
- WA test-send uses the org's connected WABA + default phone (Step-27 multi-number defaulting). Documented in test_send.py docstring.

## Self-check (10 rules)

`core/templates/`. ✓ org_id scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ Sidebar registered via registry. ✓ Permission already declared in Step 3. pack.yaml untouched. ✓ 7 files / ~400 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 5 — Test send and sidebar registration
Files: 7
Verify: WA + Email test-send work; SMS/FB/IG/push return 501; sidebar entry visible.
Tests: 8 pytest cases.
Awaiting "proceed".
```
