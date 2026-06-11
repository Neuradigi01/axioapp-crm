# Step 1 — Backend: `email_accounts` table + OAuth foundation (shared)

**Goal:** Land the per-user connected-mailbox model and the shared OAuth scaffolding that the Gmail + Microsoft adapters in Steps 2/3 will plug into. One row per (user, provider, external_account_id). Tokens encrypted at rest. Sync state tracked here.
**Track:** App Updates → Email
**Status:** Pending
**Depends on:** Phase 1.5 (permissions, audit, org settings), Phase 1.7 (audit log).

---

## Scope

In-scope:

- Alembic migration adding `email_accounts` table.
- SQLAlchemy `EmailAccount` model + Pydantic schemas (`EmailAccountConnect`, `EmailAccountRead`, `EmailAccountStatus`).
- `core/email/` sub-package skeleton:
  - `crypto.py` — Fernet symmetric encryption over `EMAIL_TOKEN_KEY` env var. Reuses pattern from `core/integrations/crypto.py`.
  - `oauth.py` — abstract `OAuthProvider` protocol (authorize URL, exchange code, refresh) + provider registry.
  - `service.py` — CRUD ops: `list_accounts(org)`, `get_account(account_id)`, `disconnect(account_id)`, `update_sync_state(account_id, cursor)`.
  - `router.py` — `GET /api/v1/email/accounts` (list), `DELETE /api/v1/email/accounts/{id}` (disconnect). Provider-specific `/connect` endpoints land in Steps 2/3.
  - `module.py` — descriptor with `menu_position=None` (no sidebar entry; managed via Settings → Email Accounts in Step 9).
- New permission keys: `email.accounts.manage` (per-user; rep connects own account), `email.accounts.admin` (Owner; can see all org accounts + disconnect others).
- Audit events: `email.account.connected`, `email.account.disconnected`.
- Tests: token roundtrip through encryption, RLS isolation, permission gates.

Out of scope:

- Provider-specific OAuth flows (Steps 2, 3).
- Sync daemon (Step 4).
- Send pipeline (Step 5).

## The `email_accounts` table

```sql
CREATE TABLE email_accounts (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                   UUID NOT NULL REFERENCES organizations(id),
    user_id                  UUID NOT NULL REFERENCES users(id),
    provider                 TEXT NOT NULL CHECK (provider IN ('gmail', 'microsoft')),
    external_account_id      TEXT NOT NULL,            -- Gmail: 'me' resolved to email; Graph: object id
    email_address            TEXT NOT NULL,            -- denormalised for matching during sync
    display_name             TEXT,
    access_token_enc         BYTEA NOT NULL,           -- Fernet-encrypted
    refresh_token_enc        BYTEA NOT NULL,
    token_expires_at         TIMESTAMPTZ NOT NULL,
    scopes_granted           TEXT[] NOT NULL,
    sync_cursor              TEXT,                     -- Gmail historyId or Graph deltaToken
    sync_state               TEXT NOT NULL DEFAULT 'pending' CHECK (sync_state IN ('pending','backfilling','live','error','disconnected')),
    last_sync_at             TIMESTAMPTZ,
    last_sync_error          TEXT,
    daily_sent_count         INT NOT NULL DEFAULT 0,
    daily_sent_reset_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    connected_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    disconnected_at          TIMESTAMPTZ,
    UNIQUE (user_id, provider, external_account_id)
);

CREATE INDEX email_accounts_org_idx ON email_accounts (org_id, sync_state);
CREATE INDEX email_accounts_email_idx ON email_accounts (org_id, lower(email_address));

ALTER TABLE email_accounts ENABLE ROW LEVEL SECURITY;
CREATE POLICY email_accounts_tenant_isolation ON email_accounts
    USING (org_id = current_setting('app.org_id', true)::uuid);
```

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_email_accounts.py` | created |
| `api/src/app/core/email/__init__.py` | created |
| `api/src/app/core/email/models.py` | created |
| `api/src/app/core/email/schemas.py` | created |
| `api/src/app/core/email/crypto.py` | created |
| `api/src/app/core/email/oauth.py` | created |
| `api/src/app/core/email/service.py` | created |
| `api/src/app/core/email/router.py` | created |
| `api/src/app/core/email/module.py` | created |
| `api/src/app/core/permissions/registry.py` | modified — register `email.accounts.manage`, `email.accounts.admin` |
| `api/src/app/main.py` | modified — include new router |
| `.env.example` | modified — add `EMAIL_TOKEN_KEY` (Fernet key, 32 bytes base64) |
| `api/tests/test_email_accounts.py` | created |

**12 files, 1 migration.** At rule-8 ceiling — new sub-package is one logical unit.

## Plan

1. Generate Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Document in `.env.example`.
2. Migration + run upgrade/downgrade locally.
3. Model + schemas. `EmailAccountRead` exposes `id`, `provider`, `email_address`, `display_name`, `sync_state`, `last_sync_at`, `last_sync_error`, `connected_at`. Tokens NEVER serialised.
4. `crypto.py`: `encrypt(plain: str) -> bytes`, `decrypt(enc: bytes) -> str`. Module-level Fernet instance.
5. `oauth.py`: `OAuthProvider` protocol with `name`, `authorize_url(state, redirect_uri)`, `exchange_code(code, redirect_uri) -> TokenSet`, `refresh(token: str) -> TokenSet`. `register_provider(name, provider)` + `get_provider(name)`. Steps 2/3 register `gmail` and `microsoft`.
6. `service.py`: standard CRUD + `refresh_if_expired(account)` helper that re-runs OAuth refresh when `token_expires_at` is within 5 min.
7. Router: list + disconnect. Disconnect zeroes tokens (don't delete the row — keep history). Audit event.
8. Tests.

## Tests

`api/tests/test_email_accounts.py`:

- **Token encryption roundtrip:** `decrypt(encrypt(s)) == s`. Encrypted bytes do not contain plain substring.
- **Account creation:** service helper `_create_for_test(user, provider, tokens)` persists with encrypted tokens.
- **RLS isolation:** Org A's accounts not visible from Org B's session.
- **Permission gate:** rep without `email.accounts.manage` → 403 on `/email/accounts`.
- **Disconnect:** zeroes tokens, sets `sync_state='disconnected'`, audit event emitted, row preserved.
- **Refresh-if-expired:** mock provider returning a new token set; verify `access_token_enc` updates and `token_expires_at` advances.

## Smoke

```powershell
docker exec template_api-api-1 uv run alembic upgrade head
docker exec template_api-api-1 uv run pytest tests/test_email_accounts.py -v

# List should be empty
$token = "<owner JWT>"
curl http://localhost:8000/api/v1/email/accounts -H "Authorization: Bearer $token"
# Expect: []
```

## Risks

- **Fernet key rotation.** If `EMAIL_TOKEN_KEY` rotates, existing rows are unreadable. Mitigation: support a `EMAIL_TOKEN_KEYS_OLD` env var with comma-separated past keys, attempted in order during decrypt. Out of scope for v1; flag for ops runbook.
- **OAuth state CSRF.** The `state` parameter passed to provider authorize URLs must be HMAC-signed with a short TTL to prevent CSRF on the callback. Step 2/3 implement this; the shared helper for it lives in `oauth.py` here.
- **Token leakage in logs.** Add a logger filter that drops any field matching `*token*` from log records before they hit stdout. Document in Step 4 (sync daemon does the heaviest logging).

## Rollback

`alembic downgrade -1` removes the table. Delete the new files. Revert permissions + main.py edits. The Gmail/Microsoft adapters in Steps 2/3 cannot persist tokens without this table — rolling back unlands the whole email track effectively.
