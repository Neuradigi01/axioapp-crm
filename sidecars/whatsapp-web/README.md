# WhatsApp Web Sidecar

Unofficial-WhatsApp (Baileys) transport pipe for Core CRM. The sidecar owns the WhatsApp Web protocol; FastAPI owns all business logic. All traffic between the two is HMAC-signed HTTP.

This step (Step 1 of the `whatsapp-unofficial` track) only scaffolds the service: HTTP server, structured logging, HMAC middleware, `/health` endpoint. Baileys, QR pairing, send/receive, and event forwarding land in Steps 2 and 3.

## Layout

```
sidecars/whatsapp-web/
├── package.json
├── tsconfig.json
├── Dockerfile
├── .env.example
├── src/
│   ├── index.ts                Express bootstrap + manager.restoreAll
│   ├── config.ts               zod env loader (fail-fast)
│   ├── logger.ts               pino + redaction
│   ├── auth.ts                 sign / verify / HMAC middleware
│   ├── sessions/
│   │   ├── types.ts            ManagedSession, SessionStatus, payload types
│   │   ├── auth-store.ts       filesystem-backed Baileys auth state (UUID-locked)
│   │   └── manager.ts          Baileys lifecycle, reconnect backoff, restoreAll
│   ├── events/
│   │   └── bus.ts              in-process EventEmitter (qr / connection events)
│   └── routes/
│       ├── health.ts           GET /health
│       └── sessions.ts         POST/GET/DELETE /sessions
└── tests/
    ├── _baileys-mock.ts        Baileys factory mock (no network)
    ├── auth.test.ts            node:test cases for HMAC
    └── sessions.test.ts        auth-store + manager + restoreAll
```

### Step 3 additions

- `src/routes/messages.ts` — `/send-text` + `/send-media`.
- `src/routes/media.ts` — `/sessions/{id}/download-media/{provider_message_id}`.
- `src/events/forwarder.ts` — bus → HMAC-signed POSTs to FastAPI.
- `src/events/translator.ts` — pure Baileys → canonical envelope.
- `src/events/retry-queue.ts` — in-memory backoff queue.
- `src/sessions/rate-limit.ts` — per-session token bucket.

## Required env vars

| Var | Purpose |
|---|---|
| `SIDECAR_PORT` | Port the sidecar listens on (default `4000`). |
| `SIDECAR_HMAC_SECRET` | Secret used to **verify** HMAC on requests **from** FastAPI. >= 32 chars. |
| `FASTAPI_BASE_URL` | FastAPI base URL, e.g. `http://localhost:8000`. Used in Step 3 to forward events. |
| `FASTAPI_HMAC_SECRET` | Secret used to **sign** HMAC on requests **to** FastAPI. >= 32 chars. |
| `LOG_LEVEL` | `debug` / `info` / `warn` / `error`. Default `info`. |
| `STORAGE_DIR` | Path to Baileys session credentials (Step 2). Default `./storage`. |
| `NODE_ENV` | `development` / `test` / `production`. Pretty logs only in non-production. |

Generate a 32-byte hex secret:

```sh
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

## Local dev

```sh
cd sidecars/whatsapp-web
cp .env.example .env
# fill SIDECAR_HMAC_SECRET and FASTAPI_HMAC_SECRET
npm install
npm run dev
```

Smoke check:

```sh
# health (no auth required)
curl http://localhost:4000/health
# -> {"status":"ok","uptime_seconds":2,"version":"0.1.0"}

# any non-health route without HMAC -> 401
curl -X POST http://localhost:4000/sessions
# -> {"error":"invalid signature"}

# with a valid signature, a non-existent route returns 404
# (proves HMAC middleware fires before the router)
BODY='{"foo":"bar"}'
SECRET=<value from .env>
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')"
curl -X POST http://localhost:4000/sessions \
  -H "Content-Type: application/json" \
  -H "X-Sidecar-Signature: $SIG" \
  -d "$BODY"
# -> {"error":"not found"} with status 404
```

## Tests

```sh
npm test
```

Covers `sign` / `verify` round-trip, tampered signature, wrong prefix, empty header, wrong secret, and body-vs-signature mismatch.

## Docker

```sh
docker build -t whatsapp-web-sidecar:dev .
docker run --rm -p 4000:4000 --env-file .env whatsapp-web-sidecar:dev
curl http://localhost:4000/health
```

## HMAC contract

Both directions sign the **raw request body** with HMAC-SHA-256 and put the digest in a header. Verification uses constant-time compare.

| Direction | Header | Secret |
|---|---|---|
| FastAPI -> Sidecar (inbound) | `X-Sidecar-Signature: sha256=<hex>` | `SIDECAR_HMAC_SECRET` |
| Sidecar -> FastAPI (outbound, Step 3) | `X-Fastapi-Signature: sha256=<hex>` | `FASTAPI_HMAC_SECRET` |

`GET /health` is exempt from HMAC so docker-compose / k8s probes can hit it.

## Production secrets

Local dev reads from `.env`. Production deploys must inject env at runtime from the same SOPS-encrypted source the FastAPI service uses (`secrets.enc.env` decrypted via `sops exec-env`). The sidecar itself just reads `process.env` — wiring is a deploy concern, not a code concern, and is **not** in scope for this step.

## Session lifecycle (Step 2)

A session is one Baileys connection to `web.whatsapp.com` bound to a `(org_id, session_id)` pair. Both ids are UUIDs — the auth-store enforces this with a regex before touching the filesystem, so a malformed id cannot escape `STORAGE_DIR`.

### Endpoints

| Method | Path | Body / Notes |
|---|---|---|
| `POST` | `/sessions` | `{ "org_id": UUID, "session_id": UUID }` — idempotent. Returns `{ session_id, org_id, status, paired, phone_number?, last_error? }`. If the session already exists, returns the current view (no re-pair). |
| `GET` | `/sessions/{session_id}` | Returns the current view. `404` if not found. **Never returns the QR data URL** — QR transport is the event bus → Step 3's forwarder → FastAPI SSE. |
| `DELETE` | `/sessions/{session_id}` | Logs out (if paired) or ends the socket (if pairing), removes the entry, deletes auth state on disk. Returns `204`. |

### States

```
pairing → connected → reconnecting → connected (loop on transient close)
        ↘ disconnected (on DisconnectReason.loggedOut — creds wiped)
```

Reconnect backoff is 5 s / 15 s / 60 s, capped at 60 s. Each reconnect emits `connection.reconnecting` on the bus. A `loggedOut` close wipes auth state and emits `connection.logged_out`; the operator must `POST /sessions` again to re-pair.

### Storage

Baileys credentials are persisted by `useMultiFileAuthState` to:

```
{STORAGE_DIR}/sessions/{org_id}/{session_id}/
```

This directory is gitignored and excluded from the Docker image. Mount it as a volume in production so a sidecar restart re-instantiates every saved session without re-scanning the QR.

### Single replica

The session manager is process-local (`Map<sessionId, ManagedSession>`). Run **one** replica per `STORAGE_DIR`. Multi-replica needs a Redis-backed ownership lock — explicitly out of scope.

### Event bus

`src/events/bus.ts` exposes typed emitters for:

| Event | Payload | Fires when |
|---|---|---|
| `qr.updated` | `{ sessionId, orgId, qrDataUrl }` | Baileys produces a new pairing string; `qrDataUrl` is a PNG data URL. |
| `connection.opened` | `{ sessionId, orgId, phoneNumber }` | First time the socket reaches `connection: 'open'` after a `qr` (or after restore). |
| `connection.logged_out` | `{ sessionId, orgId, reason }` | Baileys closes with `DisconnectReason.loggedOut`. Creds are wiped before this fires. |
| `connection.reconnecting` | `{ sessionId, orgId, attempt, reason }` | Any non-logout close. Manager schedules a recreate after backoff. |

Step 3 will subscribe to these and HMAC-POST them to FastAPI.

## Baileys version pinning

`@whiskeysockets/baileys` is pinned **exact** (no `^`) in `package.json`. WhatsApp protocol breakages typically need a Baileys bump within 24–48 h; the operator must:

1. Read the Baileys release notes.
2. Bump the version in `package.json`.
3. `npm install` and run `npm test`.
4. Smoke `POST /sessions` against a burner number.
5. Commit + redeploy.

Never use `^` or `~` here — silent transitive upgrades have caused multi-hour outages elsewhere.

## Outbound endpoints (Step 3)

All endpoints are HMAC-gated (`X-Sidecar-Signature`).

### `POST /sessions/{sessionId}/send-text`

Body:

```json
{
  "to": "919876543210",
  "body": "hello from sidecar",
  "reply_to": { "id": "<provider_message_id>", "remote_jid": "919876543210@s.whatsapp.net" }
}
```

- `to` is **digits-only**, no `+`. Sidecar appends `@s.whatsapp.net`.
- `body` ≤ 4096 chars.
- `reply_to` is optional.

Response (`200`):

```json
{ "message_id": "BAE5XXXX", "timestamp": "2026-06-30T08:00:00.000Z" }
```

Error responses:

| Status | Body | Meaning |
|---|---|---|
| `400` | `{ "error": "invalid body", "issues": [...] }` | zod validation failed. |
| `404` | `{ "error": "session not found" }` | No session with that id. |
| `409` | `{ "error": "session_not_connected", "status": "pairing" }` | Session not yet paired or reconnecting. |
| `429` | `{ "error": "rate_limited", "retry_after_seconds": 1 }` | Per-session token bucket empty. `Retry-After` header set. |
| `502` | `{ "error": "baileys_send_failed", "message": "...", "code": 500 }` | Baileys threw a Boom error. |

### `POST /sessions/{sessionId}/send-media`

Body:

```json
{
  "to": "919876543210",
  "media_type": "image",
  "base64": "<base64 bytes>",
  "mime_type": "image/jpeg",
  "filename": "photo.jpg",
  "caption": "smile"
}
```

- `media_type ∈ { image, video, audio, document }`.
- `base64` ≤ 16 MB (WhatsApp's hard cap). The Express body limit is set to 25 MB to accommodate the encoded payload plus headers.
- `mime_type` is required and must be supplied by the caller — sidecar does not sniff.
- `filename` only honoured for `document`.
- `caption` allowed for `image` / `video` / `document`.

Response shape and error responses are identical to `/send-text`.

### `GET /sessions/{sessionId}/download-media/{provider_message_id}`

FastAPI calls this when it decides to fetch the binary for a previously-received media message. The sidecar holds the last **500 inbound message references per session** in an LRU; if the id is not in the LRU, returns `404 { "error": "message not in cache" }`. Otherwise streams the decrypted media bytes with the original `Content-Type`.

### Rate limit

Per-session token bucket, **capacity 1, refill every 1.2 s** (capped, conservative — Step 8 documents tuning). Burst attempts get `429` with `Retry-After` and `retry_after_seconds`.

## Outbound events (Step 3)

Every event below is POSTed to `${FASTAPI_BASE_URL}/api/v1/integrations/whatsapp-web/events` with:

- Body: JSON.
- Header: `X-Fastapi-Signature: sha256=<hex>` over the raw body, signed with `FASTAPI_HMAC_SECRET`.
- Retry: 1 s → 5 s → 30 s → 2 min → 10 min, then drop with a `retry-queue.dropped` error log. No on-disk DLQ.

### Canonical shapes

`qr.updated`:

```json
{
  "type": "qr.updated",
  "session_id": "uuid",
  "org_id": "uuid",
  "qr_data_url": "data:image/png;base64,..."
}
```

`connection.opened`:

```json
{ "type": "connection.opened", "session_id": "uuid", "org_id": "uuid", "phone_number": "919876543210" }
```

`connection.logged_out`:

```json
{ "type": "connection.logged_out", "session_id": "uuid", "org_id": "uuid", "reason": "loggedOut" }
```

`connection.reconnecting`:

```json
{ "type": "connection.reconnecting", "session_id": "uuid", "org_id": "uuid", "attempt": 1, "reason": "connectionClosed" }
```

`message.received`:

```json
{
  "type": "message.received",
  "session_id": "uuid",
  "org_id": "uuid",
  "provider_message_id": "BAE5XXXX",
  "from": "919876543210",
  "chat_jid": "919876543210@s.whatsapp.net",
  "from_me": false,
  "timestamp": "2026-06-30T08:00:00.000Z",
  "message_type": "text|image|video|audio|document|sticker|location|contacts|reaction|unknown",
  "text": "...",
  "media": { "mime_type": "image/jpeg", "sha256": "hex", "size_bytes": 12345, "filename": "...", "caption": "..." },
  "location": { "latitude": 12.34, "longitude": 56.78, "name": "...", "address": "..." },
  "reaction": { "target_id": "BAE5YYYY", "emoji": "👍" },
  "raw": { "<full Baileys payload>": "..." }
}
```

`message.delivered` / `message.read` / `message.failed`:

```json
{
  "type": "message.delivered",
  "session_id": "uuid",
  "org_id": "uuid",
  "provider_message_id": "BAE5XXXX",
  "chat_jid": "919876543210@s.whatsapp.net",
  "timestamp": "2026-06-30T08:00:00.000Z"
}
```

### Skipped events

- **Group messages** (`*@g.us`) are dropped with a single info-log (`session.skipped_group_message`). 1:1 only in v1.
- **`fromMe: true` echoes** of our own sends are dropped — the `/send-text` response already carries the id, so re-forwarding would dedupe in FastAPI anyway.
- **Status codes 2 (PENDING) and 3 (SERVER_ACK / "sent")** are dropped — only `delivered`, `read`, `failed` are forwarded.

## restoreAll

`SessionManager.restoreAll()` runs at boot, scans `STORAGE_DIR/sessions/<orgId>/<sessionId>/`, and calls `create({orgId, sessionId})` for every directory pair that passes UUID validation. Restores are staggered (100 ms gap) so a host with thousands of sessions doesn't punch a single instantaneous burst at WhatsApp's web tier.

If a session's creds were wiped by `connection.logged_out` since the last shutdown, `restoreAll` will re-pair and emit a fresh `qr.updated`. The frontend's SSE channel (Step 6) shows this to the operator, who can re-scan.
