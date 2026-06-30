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

Future folders introduced in later steps:

- `src/routes/messages.ts` — `/send-text` + `/send-media` (Step 3).
- `src/events/forwarder.ts` — POSTs to FastAPI `/whatsapp-web/events` (Step 3).

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

## restoreAll

`SessionManager.restoreAll()` runs at boot, scans `STORAGE_DIR/sessions/<orgId>/<sessionId>/`, and calls `create({orgId, sessionId})` for every directory pair that passes UUID validation. Restores are staggered (100 ms gap) so a host with thousands of sessions doesn't punch a single instantaneous burst at WhatsApp's web tier.

If a session's creds were wiped by `connection.logged_out` since the last shutdown, `restoreAll` will re-pair and emit a fresh `qr.updated`. The frontend's SSE channel (Step 6) shows this to the operator, who can re-scan.
