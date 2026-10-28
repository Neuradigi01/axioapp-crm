# Step 3 — Sidecar outbound send + inbound event forwarding to FastAPI

**Goal:** Close the sidecar loop. Add `POST /sessions/{id}/send-text` and `/send-media` so FastAPI can ship messages out, AND build the event forwarder that POSTs inbound Baileys events (QR updates, connection state, incoming messages, delivery/read receipts) to FastAPI's `/whatsapp-web/events` endpoint with HMAC signing. Includes a small in-memory retry queue so transient FastAPI hiccups don't lose events. After this step the sidecar is feature-complete; everything else is FastAPI / frontend.
**Track:** WhatsApp Unofficial (Baileys)
**Status:** Pending
**Depends on:** Step 2 (session manager).

---

## Scope

In-scope:

- **`src/routes/messages.ts`** — two endpoints, both HMAC-gated:
  - `POST /sessions/{sessionId}/send-text` `{ to: string, body: string, reply_to?: { id: string, remote_jid: string } }`:
    - `to` is digits-only (no `+`). Sidecar appends `@s.whatsapp.net` before calling `sock.sendMessage`.
    - Returns `{ message_id, timestamp }` where `message_id` is Baileys' `result.key.id`.
    - If `sock.status !== 'connected'`, returns 409 `{ error: "session_not_connected" }`.
    - If Baileys throws (`Boom: bad-request` etc.), returns 502 with the Baileys error code.
    - **Per-session outbound rate limit**: 1 message per 1.2s (token bucket, `sock`-scoped). 429 with `retry_after_seconds` when bucket empty. Cap is intentionally conservative — Step 8 documents tuning.
  - `POST /sessions/{sessionId}/send-media` `{ to, media_type, base64, mime_type, filename?, caption? }`:
    - `media_type ∈ {image, video, audio, document}`.
    - Max base64 payload: 16 MB before decode (WhatsApp's hard cap).
    - Decodes base64 → `Buffer` → calls `sock.sendMessage(jid, { [media_type]: buffer, mimetype, fileName?, caption? })`.
    - Returns same shape as send-text.
- **`src/events/forwarder.ts`** — subscribes to the event bus from Step 2 AND adds new subscriptions for messages / receipts (registered by `manager.ts`). For each event:
  - Build a canonical payload (see "Canonical event shapes" below).
  - Sign body with `FASTAPI_HMAC_SECRET` using `auth.sign()`.
  - POST to `${FASTAPI_BASE_URL}/api/v1/integrations/whatsapp-web/events`.
  - On non-2xx OR network error: enqueue with backoff (5 retries: 1s, 5s, 30s, 2m, 10m). After 5 failures: log + drop + emit a `dlq` log line. **No on-disk DLQ** for v1 — FastAPI side is colocated, prolonged downtime means a bigger outage.
  - On 2xx: clear queue entry.
- **`src/sessions/manager.ts` extension** — register two new Baileys event handlers per session, emit to the bus:
  - `messages.upsert` `{type: 'notify' | 'append', messages: WAMessage[]}` — for each message, translate via `events/translator.ts` and emit `message.received`. Skip `fromMe: true` echoes (those are our own sends; the response from `send-text` already carries the id).
  - `messages.update` `[ {key, update: { status }} ]` — Baileys status enum: 1=ERROR, 2=PENDING, 3=SERVER_ACK (sent), 4=DELIVERY_ACK (delivered), 5=READ (read). Map and emit `message.delivered` / `message.read` / `message.failed`.
- **`src/events/translator.ts`** — pure conversion from Baileys' nested message shape to a flat canonical envelope FastAPI can persist verbatim:
  ```ts
  type CanonicalInbound = {
    type: "message.received";
    session_id: string;
    org_id: string;
    provider_message_id: string;
    from: string;                   // digits-only
    chat_jid: string;
    timestamp: string;              // ISO 8601 UTC
    message_type: "text" | "image" | "video" | "audio" | "document" | "sticker" | "location" | "contacts" | "reaction";
    text?: string;
    media?: { mime_type: string; sha256?: string; size_bytes?: number };
    location?: { latitude: number; longitude: number; name?: string; address?: string };
    reaction?: { target_id: string; emoji: string };
    raw: object;                    // full Baileys payload for debugging
  };
  ```
  - Text: pull from `message.conversation` OR `message.extendedTextMessage.text`.
  - Media: extract from `message.imageMessage` / `videoMessage` / `audioMessage` / `documentMessage`. **Binary download deferred** — sidecar emits only the metadata (mime, sha256, size). Step 6 FastAPI will call back to `/sessions/{id}/download-media` if it decides to fetch.
  - Location: `message.locationMessage`.
  - Contacts: `message.contactsArrayMessage`.
  - Reactions: `message.reactionMessage` (target id + emoji).
- **`src/routes/media.ts`** — `GET /sessions/{sessionId}/download-media/{provider_message_id}` that re-fetches a previously-received media by id using Baileys' `downloadMediaMessage`. Returns binary stream. HMAC-gated. **Called by FastAPI**, not by the browser. Sidecar holds the last 500 inbound message references in a per-session LRU so the download can find the original payload.
- **Connection-state event forwarding** — additionally emit:
  - `connection.opened` → forwarder posts `{type: 'connection.opened', session_id, org_id, phone_number}`.
  - `connection.logged_out` → `{type: 'connection.logged_out', session_id, org_id, reason}`.
  - `connection.reconnecting` → `{type: 'connection.reconnecting', session_id, org_id, attempt}`.
  - `qr.updated` → `{type: 'qr.updated', session_id, org_id, qr_data_url}`.
- **Tests** (`tests/translator.test.ts`, `tests/forwarder.test.ts`):
  - `translator.test.ts` — table-driven, one row per Baileys message type (text / image / video / location / reaction / contacts / sticker). Asserts canonical shape.
  - `forwarder.test.ts` — mock HTTP server (`node:http`) records incoming requests. Tests: happy path POST, 5xx retry-with-backoff, network error → enqueue → eventual drop after 5 failures, HMAC signature header present.
- **README update** — document all 4 sidecar endpoints (POST /sessions, GET /sessions/{id}, DELETE /sessions/{id}, POST /sessions/{id}/send-text, /send-media, GET /sessions/{id}/download-media/{id}) + the 5 outbound event types with canonical schemas.

Out of scope:

- **Ban detection.** Baileys has no explicit ban signal — we infer from `DisconnectReason.banned` (rare) or repeated `loggedOut` events from the same number. Captured as a Step 8 hardening item.
- **Group chat handling.** Baileys delivers group messages too; sidecar drops them with a single info-log (`skipped: group message`). Group support is a future track.
- **Outbound rate-limit configurability per-org.** Hardcoded to 1 msg/1.2s in this step. Step 4's table has a `rate_limit_per_sec` column that the sidecar reads at session-create time in a future iteration; for now sidecar reads the const.
- **FastAPI receiver** — that's Step 6.
- **Frontend** — Step 8.

## Files to touch

| File | Action |
|---|---|
| `sidecars/whatsapp-web/src/routes/messages.ts` | **NEW** |
| `sidecars/whatsapp-web/src/routes/media.ts` | **NEW** |
| `sidecars/whatsapp-web/src/events/forwarder.ts` | **NEW** |
| `sidecars/whatsapp-web/src/events/translator.ts` | **NEW** |
| `sidecars/whatsapp-web/src/events/retry-queue.ts` | **NEW** — in-memory backoff queue |
| `sidecars/whatsapp-web/src/sessions/manager.ts` | **MODIFY** — register messages.upsert + messages.update handlers; per-session LRU for media |
| `sidecars/whatsapp-web/src/sessions/rate-limit.ts` | **NEW** — token-bucket per session |
| `sidecars/whatsapp-web/src/index.ts` | **MODIFY** — start forwarder; mount /messages + /media routers |
| `sidecars/whatsapp-web/tests/translator.test.ts` | **NEW** |
| `sidecars/whatsapp-web/tests/forwarder.test.ts` | **NEW** |
| `sidecars/whatsapp-web/tests/rate-limit.test.ts` | **NEW** |
| `sidecars/whatsapp-web/README.md` | **MODIFY** — endpoint reference + canonical event reference |

**12 files. ~500 lines net.** Slightly over rule-8 ceiling but cohesive (one event pipeline). If review feedback wants split: messages.ts + media.ts can move into a Step 3b.

## Plan

1. **`rate-limit.ts`** — pure token bucket. `acquire(sessionId): {ok: true} | {ok: false, retry_after_ms: number}`. No external dep — `Map<sessionId, {tokens, lastRefill}>`.
2. **`translator.ts`** — one function `translate(orgId, sessionId, waMessage)`. Use a switch on the message shape. Defensive: any field absence falls back to `undefined`, never throws. The `raw` field always carries the original payload.
3. **`retry-queue.ts`** — class with `enqueue(item)`, internal `setTimeout` per item with backoff schedule, `attemptCount` per item, drop after 5. Items are functions (`() => Promise<void>`) so the queue doesn't care about content.
4. **`forwarder.ts`** — subscribe to bus events. For each event, build payload, POST. On failure, hand to retry queue.
5. **`messages.ts` route** — zod-validated bodies. Pre-flight: check session is connected. Acquire rate-limit token (or 429). Call `sock.sendMessage`. Return id.
6. **`media.ts` route** — find the message in the per-session LRU. If missing → 404. Otherwise `downloadMediaMessage` → stream response.
7. **`manager.ts` extension** — wire two new Baileys handlers, push to LRU, emit to bus.
8. **`index.ts`** — start the forwarder subscriber as part of boot. Mount new routers.
9. **Tests** — table-driven translator, mock-HTTP forwarder, rate-limit bucket.

## DB changes / migrations

**None.** Still sidecar-only. FastAPI side comes in Step 4.

## Tests

- `tests/auth.test.ts` (Step 1) — unchanged.
- `tests/sessions.test.ts` (Step 2) — unchanged.
- `tests/translator.test.ts` — 7 rows (one per message type).
- `tests/forwarder.test.ts` — 4 cases (happy 200, single 500 retry, network error retry, drop after 5 failures).
- `tests/rate-limit.test.ts` — 3 cases (under limit ok, over limit returns 429, refill after window).

## Smoke

```
1. cd sidecars/whatsapp-web
2. npm install (no new deps in this step — all stdlib)
3. npm run dev
4. Set up a mock FastAPI receiver in another shell:
     # quick python:
     python3 -m http.server 8000
     # or a slightly smarter one that prints the body
5. Pair a real WhatsApp number (Step 2 flow). Confirm status=connected.
6. Send a text:
     SECRET=<sidecar HMAC>
     BODY='{"to":"919876543210","body":"hello from sidecar"}'
     SIG="sha256=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')"
     curl -X POST http://localhost:4000/sessions/<id>/send-text \
       -H "Content-Type: application/json" \
       -H "X-Sidecar-Signature: $SIG" \
       -d "$BODY"
     -> {"message_id":"BAE5...","timestamp":"2026-..."}
     Your phone should receive "hello from sidecar".
7. Reply from your phone to the paired number with "hi back".
8. Watch the sidecar log — should show:
     event_forwarder: posted message.received -> 200
   (mock receiver shows the canonical payload)
9. Burst test (rate limit):
     for i in $(seq 1 5); do
       curl -X POST .../send-text -H "..." -d "$BODY"
     done
   Second + later calls should 429 with retry_after_seconds=1.
10. Media send (image, ~50KB):
     B64=$(base64 -i sample.jpg)
     BODY="{\"to\":\"919876543210\",\"media_type\":\"image\",\"base64\":\"$B64\",\"mime_type\":\"image/jpeg\",\"caption\":\"test\"}"
     # ... sign + POST to /send-media
     -> 200 with message_id
11. Stop the mock FastAPI receiver, send another inbound message from
    your phone, restart the receiver within 30s. Sidecar log should show
    the retry queue draining (1s → 5s → 30s).
```

## Risks

- **Base64 in /send-media**. Up to 16MB encoded = 12MB decoded. Express `json` limit was set to 10mb in Step 1 — bump to `25mb` in this step. Document why in README. Future iteration: streaming multipart upload.
- **Per-session LRU for media lookup**. 500-entry cap = ~150KB metadata in memory per session. For 1000 sessions = 150MB. Acceptable for v1. If sessions grow: lower cap to 100 or move to Redis.
- **Reaction events look like new messages to Baileys.** `messages.upsert` carries reactions as a normal message with `message.reactionMessage` set. Translator handles this; assert with a test row.
- **`sendMessage` failures.** Baileys throws `Boom` errors with HTTP-style status codes. We surface as 502 with the Baileys message. Operator-facing errors come from FastAPI (Step 5) using the same status.
- **Restart safety.** In-memory retry queue is lost on sidecar restart. For prolonged FastAPI downtime, events received during sidecar-restart-while-fastapi-down are silently lost. Acceptable trade-off for v1; production deploy should monitor sidecar health.
- **`from_me` echo skip.** A message sent via `send-text` will ALSO arrive on `messages.upsert` with `fromMe: true`. Skipping it prevents duplicate inserts. Test row.
- **Group messages.** Baileys delivers them to the same handler. Identifier check: `chat_jid.endsWith('@g.us')` → skip. Single log line, no event.

## Self-check (10 rules)

- [ ] Rule 1: No `core/` ↔ `packs/` — sidecar only.
- [ ] Rule 2: No DB changes.
- [ ] Rule 3–7: N/A.
- [ ] Rule 8: 12 files, ~500 lines — over ceiling but justified (one cohesive event-pipeline scope). Split deferred unless review demands.
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: No TODOs. Rate-limit cap is a real conservative production value. Retry queue is real with documented behaviour.

## Stop & report

```
Step 3 — Sidecar outbound send + inbound event forwarding to FastAPI

Files changed:
- 10 new files under sidecars/whatsapp-web/src/{routes,events,sessions}
  + 3 new tests
- 2 modified: src/index.ts (mount + boot forwarder), src/sessions/
  manager.ts (handlers + LRU), package.json (express limit bump),
  README (endpoints + canonical events)

What you can verify:
- All Step 1+2 tests still pass; 3 new test files pass
- Real WhatsApp send via /send-text and /send-media works end-to-end
- Inbound real WhatsApp message reaches a mock FastAPI receiver with
  the canonical payload + HMAC signature
- Rate limiter returns 429 at the documented burst rate
- Retry queue drains correctly after a transient FastAPI outage
- Group messages are silently skipped (single info log)
- Sidecar is feature-complete — no further sidecar work until Step 8
  smoke tuning

Tests added:
- tests/translator.test.ts (7 rows)
- tests/forwarder.test.ts (4 cases)
- tests/rate-limit.test.ts (3 cases)

Self-check: 10 rules, all green.

Next: Step 4 — FastAPI Alembic migration (add whatsapp_web enum value +
tbl_whatsapp_web_sessions) + module skeleton under
core/integrations/whatsapp_web/.

Awaiting your "proceed".
```
