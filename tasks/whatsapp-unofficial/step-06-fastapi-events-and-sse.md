# Step 6 — FastAPI events receiver + SSE for QR / status

**Goal:** Close the inbound loop. Sidecar already posts Baileys events to `/whatsapp-web/events`; this step builds the FastAPI side that verifies HMAC, routes by event type, and persists/dispatches. AND adds the Server-Sent Events stream `/whatsapp-web/qr-stream` that the frontend subscribes to during pairing — QR data URLs and pairing-state changes are pushed to the browser in real time without polling.
**Track:** WhatsApp Unofficial (Baileys)
**Status:** Pending
**Depends on:** Step 5 (connect endpoint + sidecar client).

---

## Scope

In-scope:

- **`POST /api/v1/integrations/whatsapp-web/events`** — sidecar → FastAPI event ingest:
  - **Unauthenticated** (no JWT) — HMAC-only.
  - Verifies `X-Sidecar-Signature` header against the raw body using `WHATSAPP_WEB_INBOUND_HMAC_SECRET`. Mismatch → 401.
  - Parses the canonical envelope (per Step 3's translator).
  - Resolves `org_id` from the body's `org_id` field — sets `app.org_id` PG session variable so RLS applies for the rest of the request.
  - Looks up `WhatsAppWebSession` by `sidecar_session_id` (the only stable join key). 404 returns to sidecar; sidecar treats 4xx as drop (no retry).
  - Routes by `type`:
    - `qr.updated` → `events.handle_qr_updated`
    - `connection.opened` → `events.handle_connection_opened`
    - `connection.logged_out` → `events.handle_connection_logged_out`
    - `connection.reconnecting` → `events.handle_connection_reconnecting`
    - `message.received` → `events.handle_message_received`
    - `message.delivered` / `message.read` / `message.failed` → `events.handle_message_status`
  - Always returns 200 fast — heavy work happens in the handler, but never block the sidecar.
- **`events.py` module** with one handler function per event type. Each handler:
  - Has a single responsibility (no business logic mixed across types).
  - Owns its own transaction.
  - Catches its own exceptions and audits failures — never rethrows into the router (sidecar would retry, causing duplicate persisted messages).
- **Event handlers:**
  - `handle_qr_updated(db, *, session, qr_data_url)`:
    - Update `WhatsAppWebSession.last_event_at = now()`, `status = 'pairing'`.
    - **Push to SSE channel** (in-memory pub/sub keyed on `integration_id`).
    - **Do not persist `qr_data_url`** — the QR is transient (rotates every ~20s), no value in DB write. Frontend subscribes to SSE for the live QR.
    - Commit + emit audit `integrations.whatsapp_web.qr_pushed`.
  - `handle_connection_opened(db, *, session, phone_number)`:
    - Update `WhatsAppWebSession`: `status='connected'`, `phone_number=...`, `last_event_at=now()`.
    - Update `Integration`: `status='connected'`, `connected_at=now()`, `account_label=phone_number`.
    - Push SSE: `{type: 'connected', phone_number}`.
    - Audit `integrations.whatsapp_web.connected`.
  - `handle_connection_logged_out(db, *, session, reason)`:
    - Update `WhatsAppWebSession`: `status='logged_out'`, `last_error=reason`.
    - Update `Integration`: `status='expired'`.
    - Push SSE: `{type: 'logged_out', reason}`.
    - Audit `integrations.whatsapp_web.logged_out`.
  - `handle_connection_reconnecting(db, *, session, attempt)`:
    - Update `WhatsAppWebSession`: `status='reconnecting'`, `last_event_at=now()`.
    - Push SSE: `{type: 'reconnecting', attempt}`.
    - **No audit** (avoid log noise for every transient reconnect).
  - `handle_message_received(db, *, session, payload)`:
    - **Reuses** `core.conversations.service.receive_webhook`. Build a synthetic `InboundMessage` from the canonical payload (text / media / location / contacts / sticker / reaction — same fields the Cloud adapter produces).
    - Call `receive_webhook(db, channel=ConversationChannel.whatsapp, inbound=inbound, received_via_phone_id=session.phone_number)`.
    - **No new conversation/message persistence code** — the existing engine handles dedupe, conversation find/create, auto-reply, keyword engine, AI handler, assignment engine (all Step 16/17/18/19 features apply to Web messages for free).
    - **Skip group messages** if any slip through (`chat_jid` ending `@g.us`) — log + drop.
  - `handle_message_status(db, *, session, payload)`:
    - Build a synthetic `WhatsAppStatusEvent` (existing dataclass in `adapters/whatsapp.py`).
    - Reuse the existing status-application path (`conversations.service.apply_status_events`).
- **SSE stream**: `GET /api/v1/integrations/whatsapp-web/qr-stream`:
  - Permission `settings.integrations.read`.
  - Returns `text/event-stream`.
  - On connect, immediately sends the current session state from DB.
  - Subscribes to the in-memory pub/sub for this org's integration_id.
  - Heartbeat every 15s (`: ping\n\n`) to keep the connection alive through proxies.
  - Closes when the client disconnects OR after 5 minutes of inactivity (pairing should complete by then; client reconnects if needed).
- **`sse_hub.py`** — tiny in-memory pub/sub:
  - `Dict[uuid.UUID, list[asyncio.Queue]]` keyed by `integration_id`.
  - `publish(integration_id, payload)` puts the payload on every subscribed queue.
  - `subscribe(integration_id)` returns an async generator that yields payloads as they arrive.
  - **Single-replica only** — multi-replica needs Redis pub/sub (deferred, mirroring sidecar's same constraint).
- **Translator code** — `events.py` includes pure helpers `_to_inbound_message(canonical) -> InboundMessage` and `_to_status_event(canonical) -> WhatsAppStatusEvent`. These translate the canonical sidecar payload (defined in Step 3) into the existing dataclasses the conversations engine already understands.
- **Tests**:
  - `test_events_router.py` — HMAC verification (valid, invalid, missing).
  - `test_events_handlers.py` — one case per handler. Each asserts the right DB writes happened AND that the conversations engine was called with the expected arguments (for `message.received`).
  - `test_sse_hub.py` — publish/subscribe round-trip; multiple subscribers see the same message; close detaches cleanly.
  - `test_sse_endpoint.py` — TestClient hits `/qr-stream`, mock publishes, assert the EventSource receives the messages.

Out of scope:

- **WhatsApp Web channel adapter** (`adapters/whatsapp_web.py`) — Step 7.
- **Dispatch shim in conversations service** — Step 7.
- **Frontend integration** — Step 8.
- **Reaction handling on the SEND side** — Step 7 (inbound reactions handled here via the existing engine).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/whatsapp_web/events.py` | **NEW** — 6 handlers + translator helpers |
| `API/src/app/core/integrations/whatsapp_web/sse_hub.py` | **NEW** — in-memory pub/sub |
| `API/src/app/core/integrations/whatsapp_web/router.py` | **MODIFY** — add `/events` POST + `/qr-stream` GET |
| `API/src/app/core/integrations/whatsapp_web/service.py` | **MODIFY** — push SSE on internal state changes too (e.g. when `connect_session` runs) |
| `API/tests/integrations/whatsapp_web/test_events_router.py` | **NEW** |
| `API/tests/integrations/whatsapp_web/test_events_handlers.py` | **NEW** |
| `API/tests/integrations/whatsapp_web/test_sse_hub.py` | **NEW** |
| `API/tests/integrations/whatsapp_web/test_sse_endpoint.py` | **NEW** |

**8 files. ~500 lines net.** At rule-8 ceiling.

## Plan

1. **`sse_hub.py`** — pure asyncio pub/sub. ~50 lines.
2. **`events.py`** — start with the 6 handlers, then the 2 translator helpers. Heaviest is `_to_inbound_message` because it maps every message type the sidecar emits. Mirror the shape `WhatsAppAdapter.parse_webhook` produces so the conversations engine doesn't need to learn a new payload shape.
3. **`router.py`** — add the 2 endpoints. SSE is the only async-generator response in this file; use FastAPI's `StreamingResponse` with `media_type="text/event-stream"`.
4. **HMAC verification** for `/events` — the body is consumed before the JSON parse; the router uses `Request.body()` raw and verifies, then `json.loads`. Mirror the existing webhook verifier pattern (`core/integrations/whatsapp/webhook.py`).
5. **`service.py` modification** — `connect_session` already updates the session row; emit an SSE `{type: 'pairing'}` so a client subscribing immediately after the POST sees state without waiting for the first QR.
6. **Tests** — TestClient + a recorder for the conversations engine (`monkeypatch receive_webhook` to capture calls and assert).

## DB changes / migrations

**None.** Step 4 already created the table; this step writes to it via the existing DAL.

## Tests

- `test_events_router.py` — 4 cases (HMAC ok / bad / missing / wrong body).
- `test_events_handlers.py` — 7 cases (one per handler + a duplicate-message dedup case).
- `test_sse_hub.py` — 3 cases (publish-subscribe, multi-subscriber, unsubscribe).
- `test_sse_endpoint.py` — 2 cases (initial state push, live publish).

## Smoke

```
1. With sidecar + FastAPI both running:
2. From browser, login + open SSE manually (devtools console):
     const es = new EventSource(
       '/api/v1/integrations/whatsapp-web/qr-stream',
       { withCredentials: true }
     );
     es.addEventListener('message', (e) => console.log(JSON.parse(e.data)));
3. In another shell: POST /connect.
4. Within 2s the EventSource should fire {type: "pairing"} and then
   shortly {type: "qr_updated", qr_data_url: "data:image/png;base64,..."}.
5. Scan the QR from your phone.
6. EventSource fires {type: "connected", phone_number: "919876543210"}.
7. Send a real WhatsApp message from your other phone to the paired
   number.
8. Inspect the API container/server logs:
   - Sidecar: "event_forwarder: posted message.received -> 200"
   - FastAPI: "events.handle_message_received: persisted msg <uuid>"
9. Open /api/v1/conversations in the app — the new conversation +
   message should appear (no UI changes yet — that's Step 8, but the
   data is there).
10. Send a reply from the CRM side — defer to Step 7 (sending wired in
    the adapter).
11. Negative path: send a POST /events with a wrong HMAC signature:
    -> 401.
12. Negative path: send /events with a known session_id but the wrong
    org_id in the body — RLS rejects, handler logs, sidecar gets 200
    (drop, no retry).
```

## Risks

- **SSE behind proxies.** Nginx / Cloudflare buffer text streams by default → SSE messages don't reach the browser. The response sets `X-Accel-Buffering: no` (nginx) + uses `\n\n` after every chunk. Document in README.
- **In-memory pub/sub == single-replica only.** Same risk as the sidecar's session manager. Multi-replica deferred.
- **HMAC validation timing.** Body must be read BEFORE FastAPI parses JSON, so the helper reads raw bytes first. Existing Meta webhook does the same — copy the pattern.
- **Group messages.** Already filtered in sidecar; double-check by asserting `chat_jid` ends with `@s.whatsapp.net` in the events handler.
- **Reusing `receive_webhook` engine.** The existing engine runs the full pipeline (auto-reply, keyword, AI, assignment). For Web messages this is **intentional** — operator gets the same automations. The only concern: auto-reply templates are Cloud-only. We pass `provider='whatsapp_web'` in the engine context so the auto-reply path falls back to free-text (no template lookup) — captured as a `~5-line` patch in the engine.
- **Duplicate `message.received` events.** Baileys' `messages.upsert` fires on multiple updates (e.g. message arrived, then read receipt). The existing engine dedupes on `channel_message_id` (UNIQUE column on `tbl_messages`). If a duplicate slips, INSERT fails with `IntegrityError` → handler swallows + audits. Cover with a test.

## Self-check (10 rules)

- [ ] Rule 1: No core ↔ packs imports.
- [ ] Rule 2: Every DB write goes through RLS-aware DAL.
- [ ] Rule 3–7: N/A.
- [ ] Rule 8: 8 files, ~500 lines.
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: No TODOs. SSE is a real production endpoint (heartbeat + reconnect-safe). Multi-replica is explicitly deferred and documented.

## Stop & report

```
Step 6 — FastAPI events receiver + SSE for QR / status

Files changed:
- 4 new files: events.py, sse_hub.py, 4 new tests
- 2 modified: router.py (2 endpoints), service.py (SSE publish on
  internal state changes)

What you can verify:
- Full real flow works: POST /connect → SSE shows pairing → QR data URL
  flows to the browser → user scans → SSE shows connected → user replies
  on phone → sidecar event lands → conversations engine persists the
  message in tbl_messages with channel=whatsapp
- Existing Conversations inbox page shows the new conversation already
  (without any UI changes in this step)
- HMAC verification on /events rejects bad signatures
- pytest -k whatsapp_web: ~26 cases green
- SSE heartbeat reaches the browser every 15s

Tests added:
- test_events_router.py (4 cases)
- test_events_handlers.py (7 cases)
- test_sse_hub.py (3 cases)
- test_sse_endpoint.py (2 cases)

Self-check: 10 rules, all green.

Next: Step 7 — WhatsApp Web channel adapter (implements ChannelAdapter
contract, calls sidecar to send) + ~10-line dispatch shim in
conversations service to pick adapter by Integration.provider.

Awaiting your "proceed".
```
