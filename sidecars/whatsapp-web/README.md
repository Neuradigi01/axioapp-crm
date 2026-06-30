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
│   ├── index.ts          Express bootstrap
│   ├── config.ts         zod env loader (fail-fast)
│   ├── logger.ts         pino + redaction
│   ├── auth.ts           sign / verify / HMAC middleware
│   └── routes/
│       └── health.ts     GET /health
└── tests/
    └── auth.test.ts      node:test cases for HMAC
```

Future folders introduced in later steps:

- `src/sessions/` — Baileys lifecycle + filesystem auth store (Step 2).
- `src/routes/sessions.ts`, `messages.ts` — connect / send (Steps 2–3).
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

## Session storage (Step 2 preview)

Baileys credentials will persist to:

```
storage/sessions/{org_id}/{session_id}/
```

This directory is gitignored and excluded from the Docker image. In Step 2 it becomes a mounted volume (or persistent claim) so a restart re-instantiates each paired session without re-scanning the QR.
