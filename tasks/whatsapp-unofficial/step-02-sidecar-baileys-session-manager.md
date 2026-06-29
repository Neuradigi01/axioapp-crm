# Step 2 — Sidecar Baileys session manager + QR pairing

**Goal:** Add Baileys to the sidecar. Implement the session manager — a process-local `Map<session_id, WASocket>` with create / get / destroy and a `useMultiFileAuthState`-backed credential store at `./storage/sessions/{org_id}/{session_id}/`. Wire `POST /sessions` to create a new session and start QR pairing. The QR string is exposed via an internal event bus (consumed by Step 3's forwarder + the temporary `GET /sessions/{id}/qr` debug endpoint).
**Track:** WhatsApp Unofficial (Baileys)
**Status:** Pending
**Depends on:** Step 1 (sidecar scaffold).

---

## Scope

In-scope:

- **Add Baileys + QR generator deps** to `package.json`:
  - `@whiskeysockets/baileys` pinned to `6.7.x` (active maintained fork; `adiwajshing/Baileys` is archived).
  - `qrcode` (for converting Baileys' pairing string to a data URL the frontend can `<img>`).
  - `@types/qrcode` (dev).
- **`src/sessions/auth-store.ts`** — thin wrapper around Baileys' `useMultiFileAuthState(path)` that:
  - Validates `org_id` + `session_id` are UUIDs (no path traversal).
  - Resolves the path to `<STORAGE_DIR>/sessions/<org_id>/<session_id>/`.
  - Exposes `loadAuthState(orgId, sessionId)` and `destroyAuthState(orgId, sessionId)`.
  - Interface-driven (`SessionStorage`) so a future Postgres-backed implementation can swap in without touching `manager.ts`.
- **`src/sessions/manager.ts`** — `SessionManager` class:
  - Process-local `Map<sessionId, ManagedSession>` where `ManagedSession = { sock, orgId, status, lastQr, lastError, paired }`.
  - `create({ orgId, sessionId })` → creates auth state, calls `makeWASocket`, wires event handlers, returns immediately (pairing is async).
  - `get(sessionId)` → returns `ManagedSession | null`.
  - `destroy(sessionId)` → `sock.logout()` (if connected) or `sock.end()` (if not), removes from map, deletes auth state on disk.
  - `restoreAll()` — called at boot: scans `<STORAGE_DIR>/sessions/*/*` and re-creates every previously-paired session so a sidecar restart never forces a re-scan.
- **Baileys event wiring inside `create`**:
  - `creds.update` → call the `saveCreds` returned by `useMultiFileAuthState` (persists to disk).
  - `connection.update` → handle 4 cases:
    - `connection: 'connecting'` → `status = 'pairing'`.
    - `update.qr` → render `qrcode.toDataURL(update.qr)`, set `lastQr`, emit `qr.updated` on the event bus.
    - `connection: 'open'` → `status = 'connected'`, `paired = true`, capture `sock.user!.id` (e.g. `"919876543210:1@s.whatsapp.net"`) → strip suffix → set on `ManagedSession.phoneNumber`, emit `connection.opened`.
    - `connection: 'close'` with `lastDisconnect.error.output.statusCode === DisconnectReason.loggedOut` → `status = 'disconnected'`, emit `connection.logged_out`, sweep auth state.
    - `connection: 'close'` with any other reason → `status = 'reconnecting'`, schedule `setTimeout(() => recreate, backoff_ms)` (5s / 15s / 60s exponential, capped at 60s).
- **`src/events/bus.ts`** — tiny event emitter (`node:events` `EventEmitter`). Typed event names:
  - `qr.updated` `{ sessionId, orgId, qrDataUrl }`
  - `connection.opened` `{ sessionId, orgId, phoneNumber }`
  - `connection.logged_out` `{ sessionId, orgId, reason }`
  - `connection.reconnecting` `{ sessionId, orgId, attempt }`
  - The Step 3 forwarder subscribes here; Step 1's HMAC contract still applies for the outgoing POST.
- **`src/routes/sessions.ts`** — three endpoints:
  - `POST /sessions` `{ org_id: UUID, session_id: UUID }` → calls `manager.create`, returns `{ session_id, status }`. **Idempotent** — calling with an existing `session_id` returns current status (does not re-create).
  - `GET /sessions/{session_id}` → returns `{ session_id, status, paired, phone_number?, last_error? }`. Used by the FastAPI status endpoint (Step 5) and the smoke flow. **No `lastQr` exposed here** — QR transport is event-bus → Step 3 forwarder → SSE only, never via REST poll.
  - `DELETE /sessions/{session_id}` → `manager.destroy`. Returns 204.
- **Boot sequence in `src/index.ts`**:
  - After Express boots, call `await manager.restoreAll()` so all previously-paired sessions auto-reconnect (no QR re-scan).
- **Tests** (`tests/sessions.test.ts`):
  - `auth-store` path resolution rejects non-UUID inputs (security: no `../` traversal).
  - `auth-store.destroyAuthState` removes the folder.
  - `manager.create` + `manager.get` + `manager.destroy` happy path with a **mocked Baileys** (`makeWASocket` swapped via a small DI hook — the real Baileys does network I/O we can't run in CI).
  - `restoreAll` walks the storage dir and re-creates every found session.
  - Event bus: subscribing to `qr.updated` fires when `connection.update` carries a `qr`.

Out of scope:

- **Send / receive messages** — Step 3.
- **Forwarder to FastAPI** — Step 3 (the bus events are emitted now, but nothing consumes them server-to-server yet — only the in-process debug helpers).
- **Ban detection / rate limiting** — Step 3.
- **Media download** — Step 3.
- **FastAPI side** — Steps 4+.
- **Real Baileys integration tests** — these need a live WhatsApp number, deferred to Step 8 smoke.

## Files to touch

| File | Action |
|---|---|
| `sidecars/whatsapp-web/package.json` | **MODIFY** — add `@whiskeysockets/baileys`, `qrcode`, `@types/qrcode` |
| `sidecars/whatsapp-web/src/sessions/auth-store.ts` | **NEW** |
| `sidecars/whatsapp-web/src/sessions/manager.ts` | **NEW** |
| `sidecars/whatsapp-web/src/sessions/types.ts` | **NEW** — `ManagedSession` / `SessionStatus` / event payload types |
| `sidecars/whatsapp-web/src/events/bus.ts` | **NEW** |
| `sidecars/whatsapp-web/src/routes/sessions.ts` | **NEW** |
| `sidecars/whatsapp-web/src/index.ts` | **MODIFY** — mount `/sessions` router; call `manager.restoreAll()` at boot |
| `sidecars/whatsapp-web/tests/sessions.test.ts` | **NEW** |
| `sidecars/whatsapp-web/tests/_baileys-mock.ts` | **NEW** — minimal Baileys mock for tests |
| `sidecars/whatsapp-web/README.md` | **MODIFY** — document `POST /sessions`, session storage layout, restoreAll behaviour |

**10 files. ~400 lines net.** At rule-8 ceiling — review pacing.

## Plan

1. **`npm install @whiskeysockets/baileys@6.7 qrcode` + `npm install -D @types/qrcode`**.
2. **`src/sessions/types.ts`**:
   ```ts
   export type SessionStatus = "pairing" | "connected" | "reconnecting" | "disconnected" | "error";
   export interface ManagedSession {
     sessionId: string;
     orgId: string;
     sock: WASocket;
     status: SessionStatus;
     paired: boolean;
     phoneNumber?: string;
     lastQr?: string;       // data URL — only set during pairing
     lastError?: string;
     reconnectAttempts: number;
   }
   ```
3. **`src/sessions/auth-store.ts`** — UUID regex check, path join with `STORAGE_DIR`, expose `loadAuthState` (returns Baileys' `{state, saveCreds}`) + `destroyAuthState` (rm -rf).
4. **`src/events/bus.ts`**:
   ```ts
   import { EventEmitter } from "node:events";
   export const bus = new EventEmitter();
   // typed wrappers so callers can't typo event names:
   export function emitQrUpdated(p: QrUpdatedPayload) { bus.emit("qr.updated", p); }
   // ...one per event
   ```
5. **`src/sessions/manager.ts`** — the heart of the step:
   - Wraps Baileys' `makeWASocket` with sensible defaults: `browser: ['CRM', 'Chrome', '1.0']`, `printQRInTerminal: false`, `logger: pino({ level: 'silent' })` (we have our own logger).
   - DI hook: `constructor(opts: { makeSocket?: typeof makeWASocket })` so tests can inject a mock.
   - `restoreAll()` walks `<STORAGE_DIR>/sessions/<orgId>/<sessionId>/` two levels deep, calls `create` for each found session (idempotent).
6. **`src/routes/sessions.ts`** — Express router, zod-validated bodies, calls into `SessionManager`.
7. **`src/index.ts`** — instantiate the singleton `SessionManager`, mount the router, await `restoreAll()` before `listen`.
8. **Tests**:
   - `auth-store.test.ts` — path-traversal regex rejection (e.g. `../etc/passwd`, `foo bar`, empty string).
   - `manager.test.ts` — `_baileys-mock` returns a fake socket with an `ev` EventEmitter; tests trigger `connection.update` events and assert manager state + bus emits.
   - `restoreAll.test.ts` — pre-create some directories, assert `manager.create` was called for each (via the mock).

## DB changes / migrations

**None.** Sidecar-only. FastAPI migration lands in Step 4.

## Tests

- `tests/auth.test.ts` (from Step 1) — unchanged, still green.
- `tests/sessions.test.ts` (new) — 6 cases as listed above.
- Run with `npm test`. All deterministic — no real WhatsApp connection.

## Smoke

```
1. cd sidecars/whatsapp-web
2. npm install (picks up the new Baileys + qrcode deps)
3. npm run dev
4. Subscribe to bus events in a debug shell:
     # in src/index.ts, while developing, temporarily log bus events:
     # bus.on('qr.updated', (p) => log.info({sess: p.sessionId}, 'QR ready'))
     # (remove the temporary listener after this smoke)
5. Create a session:
     SECRET=<sidecar HMAC>
     BODY='{"org_id":"00000000-0000-0000-0000-000000000001","session_id":"11111111-1111-1111-1111-111111111111"}'
     SIG="sha256=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')"
     curl -X POST http://localhost:4000/sessions \
       -H "Content-Type: application/json" \
       -H "X-Sidecar-Signature: $SIG" \
       -d "$BODY"
     -> {"session_id":"11111111-...","status":"pairing"}
6. Within 2-3 seconds the sidecar log should show "QR ready" (from the
   temporary debug listener) — Baileys has connected to web.whatsapp.com
   and produced a pairing string. The actual QR scan flow is exercised
   end-to-end in Step 8; here we only confirm a QR is generated.
7. Get the session status:
     curl http://localhost:4000/sessions/11111111-1111-1111-1111-111111111111 \
       -H "X-Sidecar-Signature: <sig of empty body>"
     -> {"session_id":"...","status":"pairing","paired":false}
8. Delete (cleanup):
     curl -X DELETE http://localhost:4000/sessions/11111111-... \
       -H "X-Sidecar-Signature: <sig>"
     -> 204
9. Restart smoke: scan a real QR in step 8, kill the sidecar, restart it,
   confirm log line `manager.restoreAll: 1 session restored` appears
   and `GET /sessions/{id}` returns `status: "connected"` without a
   re-scan. (Defer to Step 8 since it requires a real phone.)
```

## Risks

- **Baileys version pinning.** Pin to `6.7.x` exact (no `^`). WhatsApp protocol changes break unpinned upgrades. Document upgrade discipline in `sidecars/whatsapp-web/README.md` — operator manually bumps after testing.
- **Storage path security.** The UUID regex in `auth-store` is the only thing preventing path traversal. Lock it down — `/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i` only. Rejection returns 400 from the route, not a silent fallthrough.
- **In-memory `Map`.** Sessions don't survive process restart in memory — only the on-disk creds do. `restoreAll` rebuilds the map at boot. If the sidecar runs as multiple replicas, each replica would re-pair every session it doesn't yet have — not what we want. Sidecar is **single-replica** for v1; document this in README. Multi-replica needs a session-ownership lock (Redis), deferred.
- **`restoreAll` cost at scale.** With 1000 orgs × 1 session each = 1000 Baileys sockets at boot. Web WhatsApp tolerates this on a beefy host, but startup time grows. Stagger the restore (10 per second) — captured in the implementation as a small `await sleep(100)` between each `create` call.
- **DisconnectReason.loggedOut vs other close reasons.** Misclassifying "stream conflict" (= another device connected) as logout would wipe creds. Use Baileys' documented `DisconnectReason` constants exactly. Add a fallback `else log.warn(...)` for unknown reasons rather than treating them as logout.

## Self-check (10 rules)

- [ ] Rule 1: No `core/` ↔ `packs/` imports — sidecar is outside `api/`.
- [ ] Rule 2: No DB changes.
- [ ] Rule 3–7: N/A — sidecar is transport-only.
- [ ] Rule 8: 10 files, ~400 lines — at ceiling. Acceptable because session manager is one cohesive responsibility; splitting further would fragment.
- [ ] Rule 9: Stop and report — block below.
- [ ] Rule 10: No TODOs. Reconnect backoff is the real production logic, not a placeholder. The temporary debug `bus.on('qr.updated', ...)` log line in `index.ts` is REMOVED before the step is reported complete — only present during smoke.

## Stop & report

```
Step 2 — Sidecar Baileys session manager + QR pairing

Files changed:
- 9 new files under sidecars/whatsapp-web/src/{sessions,events,routes} +
  tests/{sessions,_baileys-mock}.ts
- 2 modified: package.json (deps), src/index.ts (mount router +
  restoreAll), sidecars/whatsapp-web/README.md (new sections)

What you can verify:
- `npm test` passes all auth + session tests
- `POST /sessions {org_id, session_id}` returns 200 and starts a real
  WhatsApp pairing (Baileys logs the connection to web.whatsapp.com)
- `GET /sessions/{id}` returns status=pairing during QR window,
  status=connected after scan
- `DELETE /sessions/{id}` removes the on-disk auth state
- Sidecar restart picks up previously-paired sessions automatically
  (verified in Step 8 smoke once we have a real phone)

Tests added:
- tests/sessions.test.ts — 6 cases (auth-store rejection, manager
  create/get/destroy with Baileys mock, restoreAll walk, bus emit)

Self-check: 10 rules, all green.

Next: Step 3 — sidecar outbound send endpoints + inbound event
forwarding to FastAPI (Baileys messages.upsert / messages.update
events become HMAC-signed POSTs to FastAPI's /whatsapp-web/events
endpoint that lands in Step 6).

Awaiting your "proceed".
```
