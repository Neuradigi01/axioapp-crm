# Step 2 — Embedded Signup backend exchange endpoint

**Goal:** Wire the backend half of Meta's Embedded Signup flow. Add a new endpoint that receives the authorization `code` + `phone_number_id` + `waba_id` from the frontend popup callback, exchanges the code for a long-lived system user access token via Meta Graph API, registers the phone number for Cloud API, subscribes the app to the WABA's webhooks, and persists everything into the existing `tbl_integrations` + `tbl_whatsapp_account_configs` rows. Customer connects without ever pasting a token or ID — fully Intercom-style.
**Track:** WhatsApp Platform Upgrade — Phase 1 (Embedded Signup)
**Status:** Pending
**Depends on:** Step 1 (Meta App Configuration ID + env vars in place).

---

## Scope

In-scope:

- **New POST endpoint** `POST /api/v1/integrations/whatsapp/embedded-signup/exchange` (under existing `core/integrations/whatsapp/router.py`).
  - Input schema (`EmbeddedSignupExchangeRequest`): `code: str`, `phone_number_id: str`, `waba_id: str`. Pydantic v2.
  - Auth gating: existing `require_permission("settings.integrations.manage")`.
  - Rate-limit: 5 attempts per org per minute (re-use existing rate-limit helper).
- **Backend orchestration steps inside the endpoint:**
  1. **Exchange code → long-lived token:** call `GET https://graph.facebook.com/{api_version}/oauth/access_token` with `client_id={META_APP_ID}`, `client_secret={META_APP_SECRET}`, `code={code}`. Receive `access_token` (short-lived business user token).
  2. **Exchange for system user token:** Meta returns a long-lived token via this same call when the code is from ES (no separate exchange call needed in v19.0+).
  3. **Fetch WABA details:** call `GET /{waba_id}?fields=id,name,verified_name,timezone_offset_min`. Capture business name.
  4. **Fetch phone number details:** call `GET /{phone_number_id}?fields=display_phone_number,verified_name,quality_rating,code_verification_status,messaging_limit_tier`. Capture the human-readable number + verified name + initial quality + tier.
  5. **Subscribe app to WABA webhooks:** call `POST /{waba_id}/subscribed_apps`. Required so Meta sends inbound messages / status updates to Core CRM's webhook URL.
  6. **Register phone number for Cloud API:** call `POST /{phone_number_id}/register` with `messaging_product=whatsapp`, `pin=<6-digit generated PIN>`. Persist the PIN (encrypted) for future 2FA changes.
  7. **Persist:**
     - Upsert `Integration` row (provider=`whatsapp`, status=`active`), with `access_token_enc` set to the encrypted long-lived token.
     - Upsert `WhatsAppAccountConfig` row with `phone_id`, `waba_id`, `display_phone_number`, `verified_name`, `api_version`, default `rate_limit_per_sec=50`, NULL `app_secret_enc` (now lives in env, see below).
     - Cache initial `WhatsAppCapacity` row: `messaging_limit_tier`, `quality_rating`, refreshed-at timestamp.
- **App secret migration to env var:**
  - Add `WHATSAPP_APP_SECRET` to [`.env.example`](API/.env.example) and `IntegrationsSettings`. Webhook signature verification reads from settings, not per-org row.
  - Existing connected orgs (rows with `app_secret_enc` set) keep working: signature verification helper falls back to per-org `app_secret_enc` if env var is empty (grandfather). New ES-connected orgs use env-side secret.
- **Service layer split:**
  - `embedded_signup.py` — orchestration above.
  - `meta_graph_client.py` — typed wrapper for the 5 Graph API calls (httpx async client, retry on 5xx, error mapping).
- **Error mapping:**
  - 400 from Meta on code exchange → `400 Bad Request` to caller with message "Embedded Signup session expired — please retry".
  - 403 from Meta on subscribed_apps or register → `403 Forbidden` with "Account not approved for management — contact support".
  - Webhook URL not yet verified at Meta → `503 Service Unavailable` with "Webhook setup incomplete — see Step 1".
  - Any other Meta error → log full response, return `502 Bad Gateway`.
- **Audit log events:**
  - `integration.whatsapp.embedded_signup.code_exchanged`
  - `integration.whatsapp.embedded_signup.completed`
  - `integration.whatsapp.embedded_signup.failed` (with reason)
- **Existing manual `POST /connect` endpoint kept as-is** for the "Advanced (self-host)" path the frontend will move behind a collapsible section in Step 3.

Out of scope:

- **Frontend popup work** — Step 3.
- **Data Deletion Callback** — Step 4.
- **Multiple phone numbers per WABA.** Current schema assumes 1 row = 1 phone. The exchange endpoint will pick the **first** phone number Meta returns from `GET /{waba_id}/phone_numbers` if multiple. Document in response: `"phone_numbers_available": N, "selected_index": 0`. Multi-number support is Phase 9.
- **Token refresh.** Long-lived system user tokens from Meta don't expire under normal conditions. No refresh logic — if Meta revokes (account disconnected from Business Manager), webhook notifies; surfacing that is Phase 4 (phone health).
- **AI / template / business profile changes.** Those are later phases.

## Files to touch

| File | Action |
|---|---|
| [`API/src/app/core/integrations/whatsapp/router.py`](API/src/app/core/integrations/whatsapp/router.py) | Add new `POST /embedded-signup/exchange` route |
| `API/src/app/core/integrations/whatsapp/embedded_signup.py` | **NEW** — orchestration service |
| `API/src/app/core/integrations/whatsapp/meta_graph_client.py` | **NEW** — Graph API typed wrapper |
| [`API/src/app/core/integrations/whatsapp/schemas.py`](API/src/app/core/integrations/whatsapp/schemas.py) | Add `EmbeddedSignupExchangeRequest`, `EmbeddedSignupExchangeResponse` Pydantic models |
| [`API/src/app/core/integrations/whatsapp/webhook.py`](API/src/app/core/integrations/whatsapp/webhook.py) | Signature verification helper: prefer env var `WHATSAPP_APP_SECRET`, fall back to per-org `app_secret_enc` |
| [`API/src/app/shared/config.py`](API/src/app/shared/config.py) | Add `whatsapp_app_secret: str = ""` to `IntegrationsSettings` |
| [`API/.env.example`](API/.env.example) | Add `WHATSAPP_APP_SECRET=` (documented as "Meta App secret — used for webhook signature verification. For ES-connected orgs, this is read from env, not per-org form.") |
| [`API/src/app/core/integrations/whatsapp/models.py`](API/src/app/core/integrations/whatsapp/models.py) | Make `app_secret_enc` nullable (already may be — confirm; if not, Alembic migration) |
| `API/alembic/versions/<timestamp>_whatsapp_app_secret_nullable.py` | **NEW (conditional)** — Alembic migration making `tbl_whatsapp_account_configs.app_secret_enc` nullable. Skip if already nullable. |
| `API/tests/integrations/test_whatsapp_embedded_signup.py` | **NEW** — pytest covering the orchestration, including mocked Graph API responses + error paths |

**~9 files (7 modified + 2-3 new). ~350 lines net.** Within rule-8 budget.

## Plan

1. **Read existing whatsapp router + connect.py** to match conventions (response model shape, error handling, audit log calls, transaction boundary).
2. **Write `meta_graph_client.py`** as a typed async wrapper:
   ```python
   class MetaGraphClient:
       def __init__(self, api_version: str, app_id: str, app_secret: str): ...
       async def exchange_code(self, code: str) -> str: ...  # returns access_token
       async def get_waba(self, waba_id: str, token: str) -> WabaInfo: ...
       async def get_phone_number(self, phone_id: str, token: str) -> PhoneInfo: ...
       async def subscribe_app_to_waba(self, waba_id: str, token: str) -> None: ...
       async def register_phone_number(self, phone_id: str, token: str, pin: str) -> None: ...
       async def list_phone_numbers(self, waba_id: str, token: str) -> list[PhoneInfo]: ...
   ```
   Use `httpx.AsyncClient` with `timeout=30s`, retry once on 5xx via existing retry helper.
3. **Write `embedded_signup.py`** as the orchestration:
   ```python
   async def complete_embedded_signup(
       db: AsyncSession,
       org_id: UUID,
       code: str,
       phone_number_id: str,
       waba_id: str,
       requester_user_id: UUID,
   ) -> EmbeddedSignupResult:
       client = MetaGraphClient(...)
       token = await client.exchange_code(code)
       waba = await client.get_waba(waba_id, token)
       phones = await client.list_phone_numbers(waba_id, token)
       selected = next((p for p in phones if p.id == phone_number_id), phones[0])
       await client.subscribe_app_to_waba(waba_id, token)
       pin = generate_six_digit_pin()
       await client.register_phone_number(selected.id, token, pin)
       # Persist
       integration = await upsert_integration(db, org_id, ...)
       config = await upsert_whatsapp_config(db, org_id, integration.id, selected, waba, pin_enc=encrypt(pin))
       await cache_capacity(db, org_id, selected.messaging_limit_tier, selected.quality_rating)
       # Audit
       await audit.log("integration.whatsapp.embedded_signup.completed", ...)
       return EmbeddedSignupResult(display_phone_number=selected.display_phone_number, ...)
   ```
4. **Wire the route** in `router.py`:
   ```python
   @router.post("/embedded-signup/exchange", response_model=EmbeddedSignupExchangeResponse)
   async def embedded_signup_exchange(
       payload: EmbeddedSignupExchangeRequest,
       db: AsyncSession = Depends(get_db),
       current_user: User = Depends(require_permission("settings.integrations.manage")),
   ):
       try:
           result = await complete_embedded_signup(
               db, current_user.org_id,
               payload.code, payload.phone_number_id, payload.waba_id,
               current_user.id,
           )
           return result
       except MetaGraphError as e:
           raise HTTPException(status_code=e.http_status, detail=e.user_message)
   ```
5. **Update webhook signature verification:**
   ```python
   def verify_signature(req_body: bytes, x_hub_signature: str, org_config: WhatsAppAccountConfig) -> bool:
       secret = settings.integrations.whatsapp_app_secret or decrypt(org_config.app_secret_enc) if org_config.app_secret_enc else None
       if not secret:
           raise ConfigurationError("No app secret configured")
       expected = hmac_sha256(secret, req_body)
       return constant_time_compare(expected, x_hub_signature)
   ```
6. **Migration** (only if needed): make `app_secret_enc` nullable. Verify current schema first; existing column may already be nullable.
7. **Tests** (`test_whatsapp_embedded_signup.py`):
   - Happy path: mock Graph API → assert DB rows persisted, audit log called.
   - Code exchange returns 400 → assert 400 response with "session expired" message.
   - Subscribe call returns 403 → assert 403 with "contact support".
   - WABA has 2 phone numbers, payload picks first → assert correct phone selected.
   - Already connected org re-runs exchange → assert update (not duplicate row).
   - Permission gate: user without `settings.integrations.manage` → 403.

## DB changes / migrations

**Conditional:** if `tbl_whatsapp_account_configs.app_secret_enc` is currently `NOT NULL`, write an Alembic migration to make it nullable. Verify by reading the existing model file before deciding.

Migration file (only if needed):
```python
def upgrade():
    op.alter_column(
        "tbl_whatsapp_account_configs",
        "app_secret_enc",
        existing_type=sa.LargeBinary(),
        nullable=True,
    )

def downgrade():
    # Backfill empty rows with placeholder before re-tightening
    op.execute("UPDATE tbl_whatsapp_account_configs SET app_secret_enc = '' WHERE app_secret_enc IS NULL")
    op.alter_column(
        "tbl_whatsapp_account_configs",
        "app_secret_enc",
        existing_type=sa.LargeBinary(),
        nullable=False,
    )
```

Run via [`API/docker-helper.cmd`](API/docker-helper.cmd) per project convention (host `uv run alembic` won't connect because `.env` password is encrypted).

## Tests

Add `API/tests/integrations/test_whatsapp_embedded_signup.py`. Mock `MetaGraphClient` with `pytest-mock` (don't hit real Graph API in CI). Coverage targets:
- Happy path (code → token → WABA → phone → subscribe → register → persist)
- 4 error cases (4xx from each Graph call)
- Permission gate
- Idempotency (re-run on already-connected org)

**No live Meta API calls in tests.** Real validation happens in the smoke section (manual).

## Smoke

After deploy + Alembic upgrade:

```
1. As an Owner of Ajay's Workspace (org 41f9ede9-41b3-44ce-b489-3004566d4068),
   open /user/integrations.

2. POST /api/v1/integrations/whatsapp/embedded-signup/exchange with a fake
   code via curl (since frontend popup isn't built yet, simulate Step 3's
   payload). Expected: 400 with "session expired" message — that's the
   correct error path for an invalid code. Confirms the endpoint is wired
   and validation works.

3. Verify the endpoint is registered:
     curl -s https://app.core-crm.com/api/v1/openapi.json | jq '.paths["/api/v1/integrations/whatsapp/embedded-signup/exchange"]'
   Should return the route's schema. Auth: Bearer token.

4. Verify audit log captures the failure:
     SELECT * FROM tbl_audit_log
     WHERE event_type = 'integration.whatsapp.embedded_signup.failed'
     ORDER BY created_at DESC LIMIT 1;

5. Confirm migration ran cleanly:
     SELECT column_name, is_nullable
     FROM information_schema.columns
     WHERE table_name = 'tbl_whatsapp_account_configs'
       AND column_name = 'app_secret_enc';
   Expected: is_nullable = 'YES'.

6. Webhook signature verification fallback works for an existing
   manually-connected org: send a test webhook event from Meta dashboard
   (Step 1's test number) → confirm signature verifies using the per-org
   stored secret (since env WHATSAPP_APP_SECRET is empty in this scenario).

7. Set WHATSAPP_APP_SECRET=<meta_app_secret> in .env, restart API,
   send another test webhook → confirm signature verifies using env var
   path (not per-org).

8. Full live test deferred to Step 3 (frontend popup → real code → real
   token → real WABA connect). Step 2 validates the plumbing in isolation.
```

## Risks

- **Token decryption uses existing Fernet key (`INTEGRATIONS_ENCRYPTION_KEY`).** Confirm key is present in dev `.env`. Missing key would surface as encryption errors at first use.
- **Graph API version pin.** If `WHATSAPP_GRAPH_API_VERSION=v19.0` but Meta deprecates v19, calls start failing in ~12 months. Add a comment + tracking issue. Bump pin annually.
- **Race condition on re-connect.** If a user already-connected hits the ES popup again, the upsert logic must update, not duplicate. Test case included.
- **Webhook subscription persistence at Meta.** If Meta loses our app's subscription (rare — usually permission revocation), incoming messages stop. Surface via a Phase 4 "phone health" widget reading `subscribed_apps` status.
- **PIN management.** The 6-digit PIN we generate during `/register` is needed if the customer later changes 2FA settings. Persist encrypted; expose in business-profile page (Phase 4) for "reveal PIN" or "rotate PIN" flow.
- **Multiple phone numbers handled silently.** If a WABA has 3 numbers, we pick the first and don't tell the customer the other 2 exist. Frontend (Step 3) should surface this: "Your WABA has 3 numbers. Connecting the first: +91 80XXX. Multi-number support coming in Phase 9."

## Self-check (10 rules)

- [ ] Rule 1: All work in `app/core/integrations/whatsapp/`. No imports from `packs/`.
- [ ] Rule 2: `tbl_whatsapp_account_configs` already has `org_id` + RLS; no new tables.
- [ ] Rule 3: Custom fields engine unaffected.
- [ ] Rule 4: No new form fields rendered on frontend — that's Step 3.
- [ ] Rule 5: Module registry untouched.
- [ ] Rule 6: Reuses existing `settings.integrations.manage` permission.
- [ ] Rule 7: `pack.yaml` untouched.
- [ ] Rule 8: ~9 files, ~350 lines.
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: Manual fallback path kept clean (not commented-out, not TODO'd — it's an explicit alternate route).

## Stop & report

```
Step 2 — Embedded Signup backend exchange endpoint

Files changed:
- API/src/app/core/integrations/whatsapp/router.py — new route
- API/src/app/core/integrations/whatsapp/embedded_signup.py — NEW orchestration
- API/src/app/core/integrations/whatsapp/meta_graph_client.py — NEW Graph wrapper
- API/src/app/core/integrations/whatsapp/schemas.py — new request/response models
- API/src/app/core/integrations/whatsapp/webhook.py — signature fallback logic
- API/src/app/shared/config.py — WHATSAPP_APP_SECRET surfaced
- API/.env.example — new env var documented
- API/src/app/core/integrations/whatsapp/models.py — nullable app_secret_enc (if needed)
- API/alembic/versions/<ts>_whatsapp_app_secret_nullable.py — NEW migration (conditional)
- API/tests/integrations/test_whatsapp_embedded_signup.py — NEW tests

What you can verify:
- POST /api/v1/integrations/whatsapp/embedded-signup/exchange registered
- Invalid code → 400 with friendly error
- Audit log captures attempt + outcome
- Schema migration applied (app_secret_enc nullable)
- Webhook signature verification still works for manually-connected orgs
- Webhook signature verification uses env WHATSAPP_APP_SECRET when set
- Pytest passes (mocked Graph API)

Tests added: 6 pytest cases in test_whatsapp_embedded_signup.py.

Self-check: 10 rules, all green.

Migration SQL (paste into prod DB if not running via Alembic):
  ALTER TABLE tbl_whatsapp_account_configs
    ALTER COLUMN app_secret_enc DROP NOT NULL;

Next: Step 3 — frontend popup flow that produces the code +
phone_number_id + waba_id payload this endpoint consumes.

Awaiting your "proceed".
```
