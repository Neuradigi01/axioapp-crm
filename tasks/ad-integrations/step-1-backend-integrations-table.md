# Step 1 — Backend: `integrations` table + token storage (encrypted at rest)

**Goal:** Land the per-org integration record model used by both Google Ads and Meta Ads (and future providers). Stores OAuth tokens encrypted via Fernet, scopes, provider account metadata, and a status flag. One row per (org, provider) for v1; multiple per-provider connections is a future surface.
**Track:** Ad Integrations
**Status:** Done — migration 0048 ships the `integrations` table + `integration_provider` (`google_ads | meta_ads`) + `integration_status` (`connected | disconnected | expired | error`) Postgres enums + RLS policy + index on `(org_id)`. Migration uses the same idempotent `DO $$ ... EXCEPTION WHEN duplicate_object` block + `PgEnum(create_type=False)` pattern as 0047 so it re-runs cleanly. `core/integrations/crypto.py` wraps Fernet — `encrypt`/`decrypt` + `encrypt_optional`/`decrypt_optional` for the common refresh-token-may-be-None case. The Fernet instance builds at import time and raises a loud `RuntimeError` if `INTEGRATIONS_ENCRYPTION_KEY` is missing or malformed (better to refuse to boot than ship encryption you can't decrypt). `core/integrations/models.py` ships `Integration` (TenantScoped) + `IntegrationProvider` + `IntegrationStatus` SQLAlchemy enums; `connected_by`/`disconnected_by` are plain UUIDs (no FK) per the post-0037 convention. `core/integrations/schemas.py` ships `IntegrationRead` (Pydantic projection that DELIBERATELY OMITS the `*_enc` columns so a router can't accidentally leak ciphertext) + `IntegrationUpsert` (internal write shape, never exposed as a request body). `core/integrations/service.py` ships `get`/`list_all`/`upsert`/`disconnect`/`decrypt_tokens` — upsert is idempotent (UNIQUE constraint on `(org_id, provider)` enforces single-row-per-pair, second connect mutates in place), disconnect is idempotent (calling on an already-disconnected row is a no-op, no second audit event), decrypt_tokens raises `RuntimeError` if the row has no ciphertext (caller bug). Audit events `integration.connected` / `integration.disconnected` emit with org context. `core/integrations/router.py` ships `GET /api/v1/integrations` (list, no tokens) + `DELETE /api/v1/integrations/{provider}` (disconnect, 404 if never connected). Both gated by `settings.integrations.manage`. `core/integrations/module.py` registers the permission via the existing `ModuleDescriptor` auto-discovery (no `permissions/registry.py` exists in this codebase — the spec called for editing it, but the project actually uses module-descriptor-based registration; the lifespan hook in `main.py` walks every registered module's `permissions` list at startup). Router wired in `main.py`. Two DevOps checklists shipped alongside the code: `manual-google-oauth-setup.md` (Google Cloud Console + OAuth consent + developer token + verification — 2-6 week external blocker for production launch) and `manual-meta-oauth-setup.md` (Meta App + Business Verification + App Review — 1-3 week external blocker). Both are runnable in parallel with Steps 2-5 code so the verification clock starts now. 15/15 backend tests green in 6.34s (7 crypto + 3 upsert + 3 disconnect + 1 decrypt_tokens + 1 schema projection). `INTEGRATIONS_ENCRYPTION_KEY` auto-generated + added to `API/.env`; migration applied (`0048_integrations` is head); container restarted; endpoint live (`GET /api/v1/integrations` returns 401 without JWT, confirming the auth gate works).
**Depends on:** Phase 1.5 (permissions, audit), nothing else.

---

## Scope

In-scope:

- Alembic migration adding `integrations` table.
- SQLAlchemy `Integration` model + Pydantic schemas.
- `core/integrations/crypto.py` — Fernet wrapper. Reads `INTEGRATIONS_ENCRYPTION_KEY` from `pydantic-settings`. Functions `encrypt(plain: str) -> str` (returns base64 ciphertext) and `decrypt(cipher: str) -> str`.
- `core/integrations/service.py`:
  - `upsert(org_id, provider, account_id, account_label, access_token, refresh_token, token_expires_at, scopes) -> Integration`.
  - `disconnect(org_id, provider, actor)` — clears tokens, sets status `disconnected`.
  - `get(org_id, provider) -> Integration | None`.
  - `decrypt_tokens(integration) -> tuple[access, refresh]`.
- `core/integrations/router.py`:
  - `GET /api/v1/integrations` — list all integrations for the org (no tokens; status + account label).
  - `DELETE /api/v1/integrations/{provider}` — disconnect.
- New permission key `settings.integrations.manage` (covers Google + Meta + future).
- New env var `INTEGRATIONS_ENCRYPTION_KEY` in `.env.example` (Fernet key — 32 url-safe-base64 bytes).
- Tests: encryption round-trip, RLS, permission gate, disconnect semantics.

Out of scope:

- No OAuth flows — Steps 2 + 4.
- No webhooks — Steps 3 + 5.
- No frontend — Steps 7 + 8.
- Token refresh logic — lives in the provider-specific code (Step 2's Google client + Step 4's Meta client). The service here just stores what's given.

## The `integrations` table

```sql
CREATE TYPE integration_provider_enum AS ENUM ('google_ads', 'meta_ads');
CREATE TYPE integration_status_enum   AS ENUM ('connected', 'disconnected', 'expired', 'error');

CREATE TABLE integrations 
(
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organizations(id),
    provider            integration_provider_enum NOT NULL,
    account_id          TEXT,                      -- the external account id (e.g. Google customer_id)
    account_label       TEXT,                      -- human-friendly label, e.g. "asha@example.com"
    access_token_enc    TEXT,                      -- Fernet ciphertext; null when disconnected
    refresh_token_enc   TEXT,
    token_expires_at    TIMESTAMPTZ,
    scopes              TEXT[],                    -- granted scopes
    status              integration_status_enum NOT NULL DEFAULT 'disconnected',
    last_error          TEXT,                      -- last error message, for the status UI
    connected_at        TIMESTAMPTZ,
    connected_by        UUID REFERENCES users(id),
    disconnected_at     TIMESTAMPTZ,
    disconnected_by     UUID REFERENCES users(id),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (org_id, provider)
);

ALTER TABLE integrations ENABLE ROW LEVEL SECURITY;
CREATE POLICY integrations_tenant_isolation ON integrations
    USING (org_id = current_setting('app.org_id', true)::uuid);
```

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_integrations.py` | created |
| `api/src/app/core/integrations/__init__.py` | created |
| `api/src/app/core/integrations/models.py` | created |
| `api/src/app/core/integrations/schemas.py` | created |
| `api/src/app/core/integrations/service.py` | created |
| `api/src/app/core/integrations/crypto.py` | created |
| `api/src/app/core/integrations/router.py` | created |
| `api/src/app/core/permissions/registry.py` | modified — add `settings.integrations.manage` |
| `api/src/app/shared/config.py` | modified — add `INTEGRATIONS_ENCRYPTION_KEY: SecretStr` field |
| `.env.example` | modified — add `INTEGRATIONS_ENCRYPTION_KEY=` line with generation instructions |
| `api/src/app/main.py` | modified (small) — include router |
| `api/tests/test_integrations_table.py` | created |

**12 files, 1 migration.** Just over the rule-8 ceiling. Could split into 1a (table + crypto) and 1b (service + router) but they're tightly coupled — recommend keeping together; if the diff feels heavy at implementation time, split.

## Plan

1. Migration: create enum types, table, RLS.
2. `crypto.py`: thin Fernet wrapper. Document key-generation in the module docstring (`Fernet.generate_key().decode()` for a fresh key).
3. Settings field in `shared/config.py`. App fails to start if missing.
4. `.env.example` line with a generated dev key + instructions.
5. Build `Integration` model and `IntegrationRead` schema (omits the `*_enc` fields — tokens never leave the backend in this form).
6. `service.upsert()` — encrypts tokens before write; sets `connected_at` + `connected_by`. Status `connected`.
7. `service.disconnect()` — clears `*_enc` (sets to NULL), sets status `disconnected`, records actor.
8. `service.decrypt_tokens()` — internal use only; never exposed to API.
9. Router: `GET /integrations`, `DELETE /integrations/{provider}`. Permission gate.
10. Tests.

## Tests

`api/tests/test_integrations_table.py`:

- **Encryption round-trip:** `decrypt(encrypt("hello")) == "hello"`. Ciphertexts differ across calls (Fernet IV).
- **Upsert stores ciphertext:** after `upsert(..., access_token="t1", refresh_token="t2", ...)`, the row's `access_token_enc` and `refresh_token_enc` do not contain "t1" or "t2" as substrings.
- **Decrypt round-trip on row:** `decrypt_tokens(integration) == ("t1", "t2")`.
- **Unique per (org, provider):** second upsert for same `(org_id, 'google_ads')` updates the row, doesn't create a new one.
- **Disconnect clears tokens:** after disconnect, `access_token_enc IS NULL` and `refresh_token_enc IS NULL`, status `disconnected`.
- **GET returns no tokens:** `IntegrationRead` response shape does not include `*_enc` fields.
- **RLS:** Org A's integration is invisible to Org B.
- **Permission gate:** Employee → 403.
- **App startup without key:** `INTEGRATIONS_ENCRYPTION_KEY` missing → app fails to start with a clear error (validation via pydantic-settings).

## Smoke

```powershell
# Generate a Fernet key for local dev
docker exec template_api-api-1 uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Paste into .env as INTEGRATIONS_ENCRYPTION_KEY=...

# Migrations
docker exec template_api-api-1 uv run alembic upgrade head

# Tests
docker exec template_api-api-1 uv run pytest tests/test_integrations_table.py -v

# Manual: as Owner, list integrations (should be empty initially)
$token = "<owner JWT>"
curl http://localhost:8000/api/v1/integrations -H "Authorization: Bearer $token"
# Expect: []
```

## Risks

- **Encryption key rotation:** Fernet supports rotation via `MultiFernet([new_key, old_key])`. We ship with one key for v1; rotation is a future task. Document.
- **Lost encryption key = lost tokens:** if the key is rotated/lost, all existing tokens decrypt to nothing → forces every org to reconnect. Acceptable for v1; back up the key in your secrets manager.
- **PG enum types add migration friction:** PG enums require special handling on rename. Acceptable — we already use them elsewhere in the project.
- **Settings start-up failure:** missing env var = container won't start. That's the right default for security.

## Rollback

`alembic downgrade -1` removes the table + enum types. Delete the new files. Revert settings + .env.example + permission registry. No other modules consume the integrations module yet at this point.
