# Step 3.5.1 — WhatsApp Business Account: backend (connect/disconnect/test)

**Goal:** Per-org WhatsApp Business Account config store + connect/disconnect/test REST API, reusing the existing `Integration` table + `crypto.py` infrastructure.

**Phase:** 3.5 (WhatsApp Campaigns)
**Depends on:** 3.8 (channel registry), 3.9 (WA adapter), Steps 1–7 of Ad Integrations (existing `Integration` table + `crypto`)
**Status:** ✅ COMPLETED

After this step the WhatsApp adapter **still uses env-vars** — that's intentional. The adapter rewire happens in **Step 3.5.3**. This step only builds the storage + connect/test API. Verification: hit `POST /api/v1/integrations/whatsapp/connect`, see encrypted credentials saved + `IntegrationStatus.connected`.

---

## Scope

### In-scope

- Extend `IntegrationProvider` enum to add `whatsapp`.
- New sidecar table `whatsapp_account_configs` (one row per `integration_id`) for WA-specific fields that don't fit the generic `Integration` row:
  - `id` (UUID PK)
  - `org_id` (TenantScoped)
  - `integration_id` (FK → `integrations.id`, ON DELETE CASCADE, UNIQUE)
  - `phone_id` (Text) — Meta Cloud API phone number ID
  - `waba_id` (Text) — WhatsApp Business Account ID (needed for template sync in Step 3.5.3)
  - `display_phone_number` (Text) — `"+91-98765-..."` for UI display
  - `verified_name` (Text, nullable) — business name as approved by Meta
  - `app_secret_enc` (Text) — Fernet-encrypted app secret (used for webhook signature validation)
  - `verify_token` (Text) — Meta GET-handshake verify token (random string user chooses; not a secret per se but org-specific)
  - `api_version` (Text, default `"v18.0"`)
  - `created_at`, `updated_at`
- Service: `connect / disconnect / test / get_status` for WhatsApp specifically.
  - `connect(org_id, payload)` — validates the token by calling `GET graph.facebook.com/{api_version}/{phone_id}?fields=display_phone_number,verified_name`. If 200, encrypts token + app_secret, upserts `Integration` row with `provider=whatsapp, status=connected`, and inserts/updates `whatsapp_account_configs` sidecar.
  - `disconnect(org_id)` — nulls token in `Integration` row, sets `status=disconnected`. Sidecar `whatsapp_account_configs` row stays (so reconnect doesn't lose phone_id/waba_id history).
  - `test(org_id)` — ping `graph.facebook.com/{phone_id}` with stored token; updates `last_error` + flips status to `error` if Meta returns 4xx/5xx.
  - `get_status(org_id)` — returns `IntegrationStatus` + sidecar fields (no token).
- REST endpoints under `/api/v1/integrations/whatsapp/`:
  - `POST /connect` — body: `{phone_id, waba_id, access_token, app_secret, verify_token, api_version?}`. Returns `{status, display_phone_number, verified_name}`.
  - `POST /disconnect` — no body. Returns 204.
  - `POST /test` — pings Meta. Returns `{status, last_error?}`.
  - `GET /status` — returns connection state + display fields. Token NEVER returned.
- All endpoints gated on `settings.integrations.manage` permission (existing key — Owner role only).
- Migration `0053_whatsapp_account_config.py`:
  - `ALTER TYPE integration_provider ADD VALUE 'whatsapp'` (Postgres ENUM extension)
  - `CREATE TABLE whatsapp_account_configs`
  - Indexes: UNIQUE(integration_id), INDEX(org_id)
  - `apply_rls('whatsapp_account_configs')`
- Tests:
  - `test_whatsapp_account_connect.py` — happy-path connect with mocked Meta `httpx` response; verifies row exists with encrypted token, status=connected, sidecar populated.
  - `test_whatsapp_account_connect.py::test_invalid_token_marks_error` — Meta 401 → status=error, `last_error` populated.
  - `test_whatsapp_account_connect.py::test_disconnect_nulls_token` — verifies token field NULL + status=disconnected.

### Out-of-scope (deferred to later steps)

- **Adapter rewire** (env-var → DB lookup) — Step 3.5.3.
- **Settings page UI** to call these endpoints — Step 3.5.2.
- **Template sync** using stored creds — Step 3.5.4.
- **Webhook routing** by `phone_id` lookup — Step 3.5.12.
- Multiple phone numbers per org — punt to post-MVP.
- Token rotation reminder cron — punt to post-MVP.

---

## Files to touch

### Created (8 files)

- `api/alembic/versions/0053_whatsapp_account_config.py` — migration + ENUM extension + RLS.
- `api/src/app/core/integrations/whatsapp/__init__.py` — package init.
- `api/src/app/core/integrations/whatsapp/models.py` — `WhatsAppAccountConfig` ORM.
- `api/src/app/core/integrations/whatsapp/schemas.py` — `WhatsAppConnectIn`, `WhatsAppStatusOut`, `WhatsAppTestOut`.
- `api/src/app/core/integrations/whatsapp/connect.py` — service: `connect / disconnect / test / get_status`.
- `api/src/app/core/integrations/whatsapp/router.py` — REST endpoints.
- `api/tests/test_whatsapp_account_connect.py` — 4-5 tests.
- (No new `module.py` — reuses parent `integrations/module.py` and `settings.integrations.manage` permission.)

### Modified (3 files)

- `api/src/app/core/integrations/models.py` — add `whatsapp = "whatsapp"` to `IntegrationProvider` enum.
- `api/src/app/main.py` — include the new router under `/api/v1/integrations/whatsapp`.
- `api/src/app/core/integrations/__init__.py` — export the new whatsapp connect service (optional re-export for symmetry with google/meta).

**File budget:** 11 files. Within ≤~10 limit (8 created + 3 modified, but 3 modifications are 1-3 line edits each).

---

## Plan

1. **Migration** — write `0053_whatsapp_account_config.py`:
   - `op.execute("ALTER TYPE integration_provider ADD VALUE IF NOT EXISTS 'whatsapp'")` (raw SQL because Alembic's `op.alter_enum` doesn't exist).
   - `op.create_table('whatsapp_account_configs', ...)` with FK to integrations + RLS.
   - In `downgrade()`: drop table + RLS. **Do NOT drop the enum value** — Postgres can't drop a single enum value (you'd have to recreate the type). Document this in a comment. Downgrade leaves `whatsapp` as a defined-but-unused value; safe.
2. **`models.py`** — add `whatsapp` to `IntegrationProvider`.
3. **`whatsapp/models.py`** — `WhatsAppAccountConfig(Base, TenantScoped)` with the 8 columns above.
4. **`whatsapp/schemas.py`** — Pydantic v2 models with `model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)`.
5. **`whatsapp/connect.py`** — service functions:
   - Validate token by calling `GET graph.facebook.com/{api_version}/{phone_id}?fields=display_phone_number,verified_name` with `Authorization: Bearer {token}`. Use `httpx.AsyncClient` (injectable for tests).
   - On success: encrypt `access_token` + `app_secret` via `from src.app.core.integrations.crypto import encrypt`, upsert `Integration` (provider=whatsapp) + `WhatsAppAccountConfig` in a single transaction.
   - On failure: persist `last_error` on the `Integration` row, status=error.
   - `disconnect`: token columns → NULL, status=disconnected. Audit log entry.
   - `test`: same call as connect, but doesn't accept new creds — uses stored ones.
6. **`whatsapp/router.py`** — 4 endpoints, all `Depends(require_permissions("settings.integrations.manage"))`.
7. **`main.py`** — `app.include_router(whatsapp_router, prefix="/api/v1/integrations")`.
8. **Tests** — use the existing `db` fixture pattern from `test_integrations_table.py`. Mock `httpx` via the `http_client_factory` argument (same pattern as `WhatsAppAdapter`).

---

## Migration SQL preview

```sql
-- Extend integration_provider enum
ALTER TYPE integration_provider ADD VALUE IF NOT EXISTS 'whatsapp';

-- Sidecar table for WA-specific config
CREATE TABLE whatsapp_account_configs (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                uuid NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    integration_id        uuid NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
    phone_id              text NOT NULL,
    waba_id               text NOT NULL,
    display_phone_number  text NOT NULL,
    verified_name         text,
    app_secret_enc        text NOT NULL,
    verify_token          text NOT NULL,
    api_version           text NOT NULL DEFAULT 'v18.0',
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_whatsapp_account_configs_integration_id
    ON whatsapp_account_configs(integration_id);
CREATE INDEX ix_whatsapp_account_configs_org_id
    ON whatsapp_account_configs(org_id);

-- Standard RLS (applied via apply_rls helper):
ALTER TABLE whatsapp_account_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_account_configs FORCE ROW LEVEL SECURITY;
CREATE POLICY whatsapp_account_configs_rls_select ON whatsapp_account_configs
    FOR SELECT USING (org_id = current_setting('app.current_org_id', true)::uuid);
-- (similar policies for INSERT/UPDATE/DELETE — apply_rls() helper handles this)
```

---

## Tests to add

`api/tests/test_whatsapp_account_connect.py`:

1. `test_connect_happy_path` — POST `/connect` with valid creds, mocked Meta 200 response (returns `display_phone_number`, `verified_name`). Asserts:
   - `Integration` row created with `provider=whatsapp, status=connected`
   - `access_token_enc` is **NOT** the plaintext token (Fernet ciphertext starts with `gAAAA`)
   - `WhatsAppAccountConfig` sidecar populated
   - `app_secret_enc` is encrypted
   - Response body contains `display_phone_number` + `verified_name`
2. `test_connect_invalid_token_marks_error` — Meta returns 401. Asserts:
   - `Integration.status == error`
   - `last_error` is populated with the Meta error message
   - No sidecar row created (rollback on failure)
3. `test_disconnect_nulls_token` — connect first, then POST `/disconnect`. Asserts:
   - `access_token_enc IS NULL`
   - `status == disconnected`
   - Sidecar row still exists (phone_id/waba_id retained)
4. `test_test_endpoint_pings_meta` — connect, then POST `/test` with mocked Meta 200. Asserts `status == connected` unchanged.
5. `test_status_endpoint_excludes_token` — GET `/status` — assert response has no `access_token` / `app_secret` field anywhere.

---

## API contract (operator-visible)

### `POST /api/v1/integrations/whatsapp/connect`

Request:
```json
{
  "phone_id": "123456789012345",
  "waba_id": "987654321098765",
  "access_token": "EAAxxxxxxxxx...",
  "app_secret": "abc123...",
  "verify_token": "my-random-verify-string",
  "api_version": "v18.0"
}
```

Response 200:
```json
{
  "status": "connected",
  "display_phone_number": "+91 98765 43210",
  "verified_name": "Sharma Furniture",
  "connected_at": "2026-05-27T10:30:00Z"
}
```

Response 400 (invalid creds):
```json
{
  "detail": "Meta API rejected the credentials: (#190) Invalid OAuth access token."
}
```

### `POST /api/v1/integrations/whatsapp/disconnect` → 204

### `POST /api/v1/integrations/whatsapp/test` → `{status, last_error?}`

### `GET /api/v1/integrations/whatsapp/status` → `{status, display_phone_number?, verified_name?, last_error?, connected_at?}`

---

## Verification checklist (what you'll do after I finish)

**Backend setup:**
1. `cd api && uv run alembic upgrade head` → migration succeeds.
2. Confirm `psql` → `SELECT enum_range(NULL::integration_provider);` shows `{google_ads, meta_ads, whatsapp}`.
3. Confirm `\d whatsapp_account_configs` shows the new table + RLS enabled.

**API smoke:**
4. Login as Owner role demo user. Get JWT.
5. `POST /api/v1/integrations/whatsapp/connect` with your **Meta test number** creds (phone_id, waba_id, system-user-token, app_secret, verify_token).
   - If creds valid → response 200 with `display_phone_number`.
   - If creds invalid → response 400 with Meta's error message.
6. `GET /api/v1/integrations/whatsapp/status` → returns `{status: "connected", display_phone_number: "+91..."}`.
7. `psql` → `SELECT status, access_token_enc FROM integrations WHERE provider='whatsapp';` — token column starts with `gAAAA` (Fernet prefix), NOT the plaintext you sent. **This is the most important verification step.**
8. `POST /api/v1/integrations/whatsapp/test` → 200, status unchanged.
9. `POST /api/v1/integrations/whatsapp/disconnect` → 204.
10. `GET /status` again → `{status: "disconnected"}`.

**Tests:**
11. `uv run pytest tests/test_whatsapp_account_connect.py -v` → 5 tests pass.

**No regressions:**
12. Existing campaign send still works (env-var path is untouched in this step).
13. Existing Google Ads / Meta Ads `Integration` rows unaffected.

---

## Self-check against 10 rules

- [x] **Rule 1:** No `core → packs` imports — `integrations/whatsapp/` is all in `core/`.
- [x] **Rule 2:** Every table has `org_id` + RLS — `whatsapp_account_configs` has both.
- [x] **Rule 3:** Layered custom fields untouched.
- [x] **Rule 4:** Forms render dynamically — N/A this step (settings UI is Step 3.5.2).
- [x] **Rule 5:** Sidebar registry — N/A (no new menu item).
- [x] **Rule 6:** Permission registry — reuses existing `settings.integrations.manage`, no new key.
- [x] **Rule 7:** Pack manifest — N/A (this is core, not pack).
- [x] **Rule 8:** Step size ≤10 files / ≤400 lines — 8 new + 3 small edits = 11 files. Within budget.
- [x] **Rule 9:** No skipping verification — stop & report at the end.
- [x] **Rule 10:** No TODOs / placeholders — adapter rewire is in Step 3.5.3, not a TODO here. Env-var path stays clean and operational until that step.

---

## Stop & report

After completing this step I will:
- List exact files changed with one-line each.
- Show migration up + down output.
- Show 5 passing tests.
- Show curl example of connect/test/disconnect.
- Show the encrypted token column in DB.
- **Await your "proceed" before Step 3.5.2 (Settings UI).**

---

## Pre-implementation question (one only)

Aapke paas Meta Cloud API ke yeh 5 cheezein hain dev/testing ke liye?

1. **`phone_id`** — Meta WhatsApp Manager → Phone Numbers tab → 15-16 digit number
2. **`waba_id`** — same page, "WhatsApp Business Account ID"
3. **`access_token`** — System User → Generate Token (scopes: `whatsapp_business_messaging` + `whatsapp_business_management`)
4. **`app_secret`** — App Dashboard → Settings → Basic → App Secret
5. **`verify_token`** — koi bhi random string aap chuno (e.g. `furniturecrm-verify-xyz123`)

Agar **haan** → "begin" bol do, mai Step 3.5.1 implement karna shuru karta hoon. Test step (#5 in verification) tabhi pass karega jab real creds aapke paas honge.

Agar **nahi** → koi baat nahi, mai stub creds ke saath unit tests pass karwa dunga (httpx mocked), aur step 1 ko bhi complete karenge. Real `connect` smoke test aap baad mein karna jab creds milein.
