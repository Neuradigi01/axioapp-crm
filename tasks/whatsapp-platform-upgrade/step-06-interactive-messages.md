# Step 6 — Interactive messages (reply buttons + CTA buttons + list)

**Goal:** Send Meta-spec interactive messages from the conversation composer — quick-reply buttons (max 3), call-to-action buttons (URL or phone), and list messages (up to 10 items in sections). Recipient taps → reply event lands as inbound message in Core CRM with metadata pointing at which button/list-item was selected.
**Status:** COMPLETED (code) — pending migration apply when DB is back online
**Depends on:** Step 5 (composer pattern established).

---

## Scope

In-scope:
- Add `tbl_conversation_messages.interactive_payload JSONB` column on outbound messages.
- Webhook handler: parse `button_reply` / `list_reply` events from Meta → store as inbound text with `meta: { reply_to_button_id, reply_to_list_item_id, original_message_id }`.
- Outbound send: build Meta interactive payload (`type: interactive`, `interactive: { type: button|list, ... }`).
- Composer "+" menu → "Interactive message" → modal:
  - Type picker: Reply buttons / CTA buttons / List.
  - Reply buttons: up to 3, each with title (max 20 chars) + payload (max 256 chars).
  - CTA buttons: URL or phone (max 2 per Meta spec — but enforce 1 to stay safe).
  - List: section title + up to 10 rows, each with title + optional description + payload.
  - Live preview pane.
- Thread renders interactive messages with button labels visible (not just JSON).
- Inbound reply messages render with "Reply to: <button label>" attribution.

Out of scope:
- Flow (form) messages — Step 25.
- Catalog messages — out of core (vertical-pack only).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/conversations/models.py` | Add `interactive_payload JSONB` |
| `API/alembic/versions/<ts>_conversation_interactive_payload.py` | **NEW** migration |
| `API/src/app/core/conversations/adapters/whatsapp.py` | Build interactive payload per Meta spec |
| `API/src/app/core/conversations/adapters/whatsapp.py` (parse_webhook) | Parse `button_reply` / `list_reply` events |
| `API/src/app/core/conversations/schemas.py` | `InteractivePayload` Pydantic model |
| `APP/.../conversations/composer/composer.component.ts` | "+" menu integration |
| `APP/.../conversations/composer/interactive-builder.component.ts` | **NEW** builder modal |
| `APP/.../conversations/thread/message-bubble.component.ts` | Render interactive messages + reply attribution |
| `API/tests/conversations/test_whatsapp_interactive.py` | **NEW** |

**~9 files. ~450 lines.**

## Plan

1. Migration: add JSONB column, nullable, indexed only on `(org_id, conversation_id)`.
2. Build `InteractivePayload` schema with discriminated union: `ButtonReplyPayload`, `CtaButtonPayload`, `ListPayload`.
3. Extend `WhatsAppAdapter.send()` — if interactive present, build Meta-spec body. Persist payload in `interactive_payload` column for replay/audit.
4. Webhook parse: detect `interactive.button_reply` / `interactive.list_reply` → create inbound text message with reply attribution.
5. Frontend builder: signal-driven form with live preview; validation per Meta limits.
6. Bubble render: button row layout for sent interactive; "↳ Reply to: <label>" for inbound replies.
7. Tests: build payload shapes, parse webhook events, length limits enforced.

## DB changes / migrations

`tbl_conversation_messages.interactive_payload JSONB NULL`. Down-migration drops column.

## Tests

7 pytest cases — 3 outbound shapes + 2 inbound parse paths + 2 validation rejection paths.

## Smoke

```
1. Conversation → "+" → Interactive → Reply buttons. Add Yes / No / Maybe. Send.
2. On recipient's WhatsApp: tap "Yes" → conversation receives "Yes" inbound with attribution.
3. Repeat with CTA URL button (test link) → tap → opens URL in browser.
4. Repeat with List message of 4 furniture categories → tap → receives selection inbound.
5. Try 4-button payload → builder rejects with "max 3".
6. Existing text + media + template sends still work.
```

## Risks

- Meta enforces strict char limits — validation must match exactly or sends get rejected.
- iOS / Android render interactive slightly differently; smoke on both.
- Inbound reply payload includes both `id` and `title` — store both; UIs may need `id` for routing, `title` for display.

## Self-check (10 rules)

- [ ] All `core/conversations/`. ✓ Rule 1
- [ ] org_id + RLS preserved. ✓ Rule 2
- [ ] No custom-field changes. ✓ Rule 3
- [ ] Static builder form. ✓ Rule 4 N/A
- [ ] No registry change. ✓ Rule 5
- [ ] Reuses `conversations.send`. ✓ Rule 6
- [ ] pack.yaml untouched. ✓ Rule 7
- [ ] 9 files, ~450 lines. ✓ Rule 8
- [ ] Stop and report. ✓ Rule 9
- [ ] No TODOs. ✓ Rule 10

## Stop & report

```
Step 6 — Interactive messages
Files: 9
Verify: build + send reply buttons / CTA / list; inbound replies attribute to source button; length limits enforced.
Tests: 7 pytest cases.
Next: Step 7 — reply/quote + reactions.
Awaiting "proceed".
```
