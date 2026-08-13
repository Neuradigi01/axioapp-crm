# Step 7 — Message nodes: Text Button + Media Button + List + Template + WA interactive send methods

**Goal:** Ship the four core send-capable node types (Text Button, Media Button, List, Template) plus stubs for the three commerce nodes (Catalog / Single / Multi Product), extending the WhatsApp adapter with real interactive-message send methods and Baileys numbered-text fallbacks.
**Depends on:** Steps 6 (engine)
**Status:** Pending

## Scope

**In-scope**
- `core/chatbots/nodes/text_button.py`, `media_button.py`, `list.py`, `template.py`.
- Stubs (visible in palette, disabled empty-state at edit-time): `catalog_message.py`, `single_product.py`, `multi_product.py`.
- Node registry auto-registration.
- Extend `conversations/adapters/whatsapp.py:WhatsAppAdapter` with `send_interactive_buttons(...)`, `send_interactive_list(...)`.
- Extend `WhatsAppWebAdapter` (Baileys) with numbered-text fallback methods (same signatures).
- WA 24h session-window check on send; outside window → `session_expired` port OR auto-substitute Template if configured on the node.
- Per-channel answer escaping (HTML for email, JSON-string for WA interactive payloads).
- Implicit output ports on Text Button / Media Button (one per button, max 3) and List (one per row, max 10).
- Outbound message rows tagged with `chatbot_run_id` FK (populated so human-takeover detection in Step 6 works).

**Out of scope**
- Ask-* nodes — Step 8.
- Email-fallback signed URLs for Text Button on email — Step 11 (until then, email Text Button node is disabled OR falls back to plain text listing options).

## Files to touch

- `API/src/app/core/chatbots/nodes/__init__.py` (created — node registry)
- `API/src/app/core/chatbots/nodes/text_button.py` (created)
- `API/src/app/core/chatbots/nodes/media_button.py` (created)
- `API/src/app/core/chatbots/nodes/list.py` (created)
- `API/src/app/core/chatbots/nodes/template.py` (created)
- `API/src/app/core/chatbots/nodes/catalog_message.py` (created — stub raising `NodeNotAvailable`)
- `API/src/app/core/chatbots/nodes/single_product.py` (created — stub)
- `API/src/app/core/chatbots/nodes/multi_product.py` (created — stub)
- `API/src/app/core/chatbots/channel_bridge.py` (extended)
- `API/src/app/core/conversations/adapters/whatsapp.py` (modified — interactive send methods)

## Plan

1. Node registry — `register_node(type, handler)` pattern; each node file calls `register_node("text_button", handle)` at module bottom; `nodes/__init__.py` imports all files for side-effect registration.
2. `NodeHandler` signature: `def handle(run: ChatbotRun, node: Node, context: dict) -> NodeResult` per Step 6.
3. `text_button.py`:
   - Validate: message body ≤1024 chars, buttons 1-3, each button label ≤20 chars.
   - Session-window check (via channel_bridge helper).
   - Escape `{{answers.<id>}}` variables per-channel (JSON-string for WA, HTML for email).
   - Send via WA Cloud API `interactive.button` OR Baileys numbered-text fallback OR Email HTML (signed URL support lands in Step 11).
   - Persist outbound `Message` with `chatbot_run_id`.
   - Return `NodeResult(park_key=("button_click", conversation_id, run_id), ...)`.
4. `media_button.py` — similar to text_button but with header media (image/video/document) via WA `media_id` only (Decision §16 — no URL fetch); operator uploads media via existing CRM file storage which returns a media_id after WA registration.
5. `list.py` — WA `interactive.list` payload; up to 10 rows across up to 10 sections; one output port per row.
6. `template.py` — reuses `core/templates/` — pick approved template by id; variable bindings for `{{1}}, {{2}}, ...` filled from `answers.*` and `contact.*`; unapproved template rejected at save-time.
7. Interactive send extensions on `WhatsAppAdapter`:
   - `send_interactive_buttons(org_id, external_id, body_text, buttons, header=None, footer=None) → ChannelMessageRef`
   - `send_interactive_list(org_id, external_id, body_text, sections, header=None, footer=None) → ChannelMessageRef`
   - Both hit Meta's `messages` endpoint with `type=interactive`.
8. Baileys fallback on `WhatsAppWebAdapter`:
   - `send_interactive_buttons` → sends `body_text + "\n\nReply 1 for X\nReply 2 for Y\nReply 3 for Z"`.
   - Numbered-reply parsing lands in Step 8's Ask-question resume logic (reused pattern).

## DB changes / migrations

None (schema pre-provisioned).

## Tests to add

Location: `API/tests/core/chatbots/test_nodes_messages.py`

- `test_text_button_wa_cloud_sends_interactive_payload` (T14)
- `test_text_button_baileys_fallback_numbered_text` (T15)
- `test_text_button_email_sends_html` (email path; signed URLs stubbed until Step 11)
- `test_list_wa_sends_interactive_list_with_rows` (T20)
- `test_template_send_approved_template` (T21)
- `test_template_send_unapproved_rejected_at_save` (T21)
- `test_message_body_over_1024_chars_rejected_at_save`
- `test_buttons_over_3_rejected_at_save`
- `test_list_rows_over_10_rejected_at_save`
- `test_wa_send_outside_24h_window_takes_session_expired_port` (T33)
- `test_wa_send_outside_24h_window_falls_back_to_template_when_configured` (T33)
- `test_outbound_message_has_chatbot_run_id_set` (T14)
- `test_answer_escaped_html_in_email_body` (M4 — no XSS injection via customer text)
- `test_answer_escaped_json_string_in_wa_interactive_payload` (M4)
- `test_catalog_single_multi_product_nodes_raise_not_available` (stub verification)

## Verification checklist

**Backend**
- [ ] Send a real WA interactive button message via test-fire → renders correctly on a test WA number.
- [ ] Send via Baileys-provider org → numbered text arrives.
- [ ] Outside-window send lands in the `session_expired` port.
- [ ] Test-fire diagnostics show correct payload for each node type.

**Frontend** — N/A.

**Code review**
- [ ] WA Cloud API adapter methods use `media_id` for header media, never a fetched URL (SSRF hardening).
- [ ] Per-channel escaping applied at the render boundary in `channel_bridge.py`.
- [ ] Node registry auto-registers on import.

## Self-check (10 rules)

- [ ] `core` didn't import `packs`
- [ ] `org_id` scoped in every send
- [ ] Sidebar/permissions N/A
- [ ] Reuse — reused existing `WhatsAppAdapter`, `core/templates/` variable engine
- [ ] Query efficiency — session-window check is a single indexed query
- [ ] Under 10 files, under 400 lines (may need to split if it grows — split into two steps if over)
- [ ] Zero TODOs

## Stop & report

Report actual send payloads sent to Meta for each node type (redact credentials), sample outbound message rows with `chatbot_run_id`, and a test-fire transcript for a 3-button flow. Await "proceed".
