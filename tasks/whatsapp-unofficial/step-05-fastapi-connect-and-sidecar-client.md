# Step 5 — FastAPI connect / disconnect / status + sidecar HTTP client

**Goal:** Wire the FastAPI side that orchestrates the WhatsApp Web pairing flow. Add 3 endpoints (`/connect`, `/disconnect`, `/status`) under `/api/v1/integrations/whatsapp-web/` and the HMAC-signed HTTPX wrapper that calls the sidecar. After this step an operator can hit `/connect`, the backend tells the sidecar to start a session, and `/status` reflects the live pairing state — though QR delivery to the browser is still pending (Step 6 SSE).
**Track:** WhatsApp Unofficial (Baileys)
**Status:** Pending
**Depends on:** Step 4 (migration + module skeleton).

---

## Scope

In-scope:

- **`sidecar_client.py`** — HTTPX async client wrapper:
  - Reads `WHATSAPP_WEB_SIDECAR_URL` + `WHATSAPP_WEB_SIDECAR_HMAC_SECRET` from config.
  - One class `SidecarClient` with methods:
    - `create_session(org_id, sidecar_session_id)` → `{session_id, status}`
    - `get_session(sidecar_session_id)` → `{session_id, status, paired, phone_number?, last_error?}`
    - `delete_session(sidecar_session_id)` → 204
    - `send_text(sidecar_session_id, to, body, reply_to=None)` → `{message_id, timestamp}` (used in Step 7)
    - `send_media(sidecar_session_id, to, media_type, base64, mime_type, ...)` → `{message_id, timestamp}` (Step 7)
    - `download_media(sidecar_session_id, provider_message_id)` → bytes (Step 7)
  - Every method signs the request body with HMAC-SHA256 → `X-Sidecar-Signature: sha256=<hex>` header. Same algorithm as `auth.sign` in the sidecar.
  - On 5xx + network errors → raises `SidecarUnavailable` with context (the service layer maps to 502 Bad Gateway).
  - On 409 (`session_not_connected`) → raises `SessionNotConnected`.
  - On 429 (rate-limited by sidecar) → raises `SidecarRateLimited` with `retry_after_seconds` parsed from the response.
  - `timeout=10.0` default; bumped to `30.0` for media calls.
- **`schemas.py` extensions** — add request schemas for the new endpoints:
  - `WhatsAppWebConnectRequest` — no body (the connect flow doesn't need any input today; future revisions might carry a label).
  - `WhatsAppWebSessionOut` — already drafted in Step 4; extended here with `qr_data_url: str | None` (used by Step 6 SSE, but the field shape lands here so the schema is stable).
- **`service.py`** — three orchestration functions, all `async`, all owning their transactions per layered rule:
  - `connect_session(db, *, actor_id) -> WhatsAppWebSessionOut`:
    1. **Idempotency**: if an `Integration` row already exists for this org with `provider=whatsapp_web` and `status=connected`, raise `AlreadyConnected` (the router maps to 409 with a hint to disconnect first).
    2. Upsert an `Integration` row: `provider=whatsapp_web`, `status=disconnected`, `connected_by=actor_id`, freshly generated `webhook_secret`.
    3. Generate `sidecar_session_id = uuid4().hex`.
    4. Upsert `WhatsAppWebSession` row: `integration_id`, `sidecar_session_id`, `status='pending'`.
    5. `db.flush()` (so any later step can read the row inside this transaction).
    6. Call `sidecar_client.create_session(...)`. On `SidecarUnavailable`: mark session row `status='error'`, persist `last_error`, `db.commit()`, re-raise as 502.
    7. On sidecar 200: update session row `status='pairing'`, `db.commit()`, `db.refresh(...)`.
    8. Emit audit event `integrations.whatsapp_web.connect_initiated`.
    9. Return the session as `WhatsAppWebSessionOut`.
  - `disconnect_session(db, *, actor_id)`:
    1. Load the `Integration` + `WhatsAppWebSession` by org.
    2. If none → 404.
    3. Call `sidecar_client.delete_session(...)` — wrap in try/except so a sidecar 502 doesn't block local cleanup.
    4. Update session row `status='disconnected'`, null `phone_number`.
    5. Update `Integration` row: `status=disconnected`, `disconnected_by=actor_id`, `disconnected_at=now()`.
    6. Audit `integrations.whatsapp_web.disconnected`.
    7. Commit.
  - `get_status(db) -> WhatsAppWebSessionOut | None`:
    1. Load the `Integration` + `WhatsAppWebSession` by org. None → None.
    2. **Liveness check** — if session row `last_event_at < now() - 60s` AND `status='connected'`, call `sidecar_client.get_session(...)` to refresh the cached state (best-effort, swallowed on failure).
    3. Return the projection.
- **`router.py`** — 3 endpoints:
  - `POST /connect` — permission `settings.integrations.manage`. Calls `service.connect_session`. Returns 200 with `WhatsAppWebSessionOut`.
  - `POST /disconnect` — same permission. Calls `service.disconnect_session`. Returns 204.
  - `GET /status` — permission `settings.integrations.read` (existing). Returns 200 with `WhatsAppWebSessionOut | null`.
  - Error mapping:
    - `AlreadyConnected` → 409 `{detail, hint}`.
    - `SidecarUnavailable` → 502 `{detail}`.
    - `SessionNotConnected` → 409.
- **`data_access.py`** — extend with:
  - `set_session_status(db, *, integration_id, status, **patches)` — pure UPDATE.
  - `delete_session(db, *, integration_id)` — pure DELETE.
- **Tests**:
  - `test_sidecar_client.py` — uses `respx` (already in repo for Meta tests) to mock the sidecar:
    - HMAC signature header present and correct for each method.
    - 200 happy path returns the parsed body.
    - 502 raises `SidecarUnavailable`.
    - 429 raises `SidecarRateLimited` with correct `retry_after`.
  - `test_service.py` — async pytest cases:
    - `connect_session` happy path inserts both rows + calls sidecar.
    - `connect_session` when already connected raises `AlreadyConnected`.
    - `connect_session` when sidecar 502s leaves session row in `status='error'`.
    - `disconnect_session` cleans both rows even if sidecar 502s.
    - `get_status` returns null when no integration exists.
  - `test_router.py` — TestClient-level:
    - `POST /connect` without auth → 401.
    - `POST /connect` without the permission → 403.
    - `POST /connect` happy path → 200 with shape.

Out of scope:

- **Events receiver** (`/whatsapp-web/events`) — Step 6.
- **SSE for QR** — Step 6.
- **Channel adapter (send messages via the new provider)** — Step 7.
- **Dispatch shim in conversations service** — Step 7.
- **Frontend** — Step 8.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/whatsapp_web/sidecar_client.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp_web/schemas.py` | **MODIFY** — add request schemas + `qr_data_url` field |
| `API/src/app/core/integrations/whatsapp_web/service.py` | **MODIFY** — 3 orchestration functions |
| `API/src/app/core/integrations/whatsapp_web/data_access.py` | **MODIFY** — add 2 helpers |
| `API/src/app/core/integrations/whatsapp_web/router.py` | **MODIFY** — wire 3 endpoints |
| `API/src/app/core/integrations/whatsapp_web/exceptions.py` | **NEW** — `AlreadyConnected`, `SidecarUnavailable`, `SessionNotConnected`, `SidecarRateLimited` |
| `API/tests/integrations/whatsapp_web/test_sidecar_client.py` | **NEW** |
| `API/tests/integrations/whatsapp_web/test_service.py` | **NEW** |
| `API/tests/integrations/whatsapp_web/test_router.py` | **NEW** |

**9 files. ~400 lines net.** At rule-8 ceiling.

## Plan

1. **`exceptions.py`** — small file, 4 classes.
2. **`sidecar_client.py`** — central HTTPX wrapper:
   ```python
   class SidecarClient:
       def __init__(self, *, base_url: str, hmac_secret: str, timeout: float = 10.0):
           self._base = base_url.rstrip("/")
           self._secret = hmac_secret
           self._timeout = timeout

       def _sign(self, body: str) -> str:
           return "sha256=" + hmac.new(
               self._secret.encode(), body.encode(), hashlib.sha256
           ).hexdigest()

       async def _post(self, path: str, payload: dict, *, timeout: float | None = None) -> dict:
           body = json.dumps(payload, separators=(",", ":"))
           headers = {"Content-Type": "application/json", "X-Sidecar-Signature": self._sign(body)}
           async with httpx.AsyncClient(timeout=timeout or self._timeout) as client:
               resp = await client.post(f"{self._base}{path}", content=body, headers=headers)
           # map status codes per spec ...
   ```
   Centralise the body-serialisation + signing so individual methods stay clean.
3. **`service.py`** — write each function exactly per the spec. Transaction discipline: every commit happens here, never in DAL.
4. **`router.py`** — three thin endpoints that resolve auth, get a DB session, call the service.
5. **`data_access.py`** — add the 2 helpers. Stay pure CRUD.
6. **Tests** — `respx` for HTTP mocking, `pytest-asyncio` for the async service tests. Reuse existing conftest helpers for org/user fixtures.

## DB changes / migrations

**None.** Schema was created in Step 4. This step writes to it.

## Tests

- `test_sidecar_client.py` — 4 cases.
- `test_service.py` — 5 cases.
- `test_router.py` — 3 cases.
- All run via `uv run pytest -k whatsapp_web`.

## Smoke

```
1. Start the sidecar (Step 1-3 setup):
     cd sidecars/whatsapp-web && npm run dev
2. Start FastAPI:
     cd API && run start
3. Acquire a JWT for an org with settings.integrations.manage permission
   (existing test helper or login flow).
4. POST connect:
     curl -X POST http://localhost:8000/api/v1/integrations/whatsapp-web/connect \
       -H "Authorization: Bearer $JWT"
     -> 200 {
         "id": "<session-uuid>",
         "status": "pairing",
         "phone_number": null,
         ...
       }
   Sidecar log shows "session created, pairing started".
5. GET status (within 2s of step 4):
     curl http://localhost:8000/api/v1/integrations/whatsapp-web/status \
       -H "Authorization: Bearer $JWT"
     -> {"status": "pairing", ...}
6. Re-POST connect — should 409:
     -> {"detail": "Already connected.", "hint": "Disconnect first."}
7. POST disconnect:
     curl -X POST .../disconnect -H "..."
     -> 204
   Sidecar log shows session destroyed; auth state folder removed.
8. GET status now:
     -> null (or {"status":"disconnected"}, depending on retention policy)
9. Kill the sidecar (simulate downtime) and try POST connect:
     -> 502 {"detail": "WhatsApp Web sidecar unavailable. Try again in
              a moment."}
   Session row state should be 'error' with last_error populated.
```

## Risks

- **Transaction boundary mistake.** `service.connect_session` writes to 2 tables AND calls an external HTTP service. If the order is wrong (HTTP call before DB flush), a sidecar success with a DB rollback would orphan a sidecar session. Correct order: DB upsert → flush (not commit) → HTTP call → commit on HTTP success, OR `set last_error + commit` on HTTP failure. The test must include a `respx` failure case to pin this.
- **HMAC secret mismatch.** Sidecar's `SIDECAR_HMAC_SECRET` and FastAPI's `WHATSAPP_WEB_SIDECAR_HMAC_SECRET` must be the same value. Document in both sidebar `.env.example` and FastAPI `config.env` that they're a paired secret.
- **Idempotency on re-connect**. Pressing "Connect" twice within a few seconds must be safe — once 409, twice 409, not "two sidecar sessions". The check on `IntegrationStatus.connected` covers the steady-state case; for the in-flight `status='pairing'` case, we also short-circuit (returns current session instead of creating a new one — small refinement in `connect_session`).
- **Session row leak on partial failure.** If the FastAPI process crashes between DB upsert and sidecar call, the session row sits in `status='pending'` forever. Mitigation: a Celery janitor that sweeps `pending` rows older than 5 minutes and either retries the sidecar call or marks them `error`. **Deferred** to a Step 8 hardening item.

## Self-check (10 rules)

- [ ] Rule 1: No core ↔ packs imports.
- [ ] Rule 2: All writes carry `org_id` via `TenantScoped`. RLS applies.
- [ ] Rule 3–7: N/A this step.
- [ ] Rule 8: 9 files, ~400 lines.
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: No TODOs. Janitor task is **explicitly deferred to Step 8**, not left as a TODO.

## Stop & report

```
Step 5 — FastAPI connect / disconnect / status + sidecar HTTP client

Files changed:
- 2 new module files (sidecar_client.py, exceptions.py)
- 4 modified module files (schemas.py, service.py, data_access.py,
  router.py)
- 3 new test files

What you can verify:
- POST /api/v1/integrations/whatsapp-web/connect creates Integration +
  WhatsAppWebSession rows AND calls sidecar to start pairing
- GET /status returns live state of the session
- POST /disconnect tears down both sides
- Double-connect attempts are 409, not duplicate sessions
- Sidecar downtime produces a clean 502 with persisted error state
- All HMAC headers verified on the sidecar side
- pytest -k whatsapp_web: 12 cases green

Tests added:
- test_sidecar_client.py (4 cases)
- test_service.py (5 cases)
- test_router.py (3 cases)

Self-check: 10 rules, all green.

Next: Step 6 — FastAPI events receiver (Baileys events arrive at
/whatsapp-web/events) + SSE stream for the frontend to receive QR
updates in real time.

Awaiting your "proceed".
```
