"""core.email — connected-mailbox foundation.

Step 1 lands the per-user `email_accounts` table + the OAuth scaffolding
that the Gmail (Step 2) and Microsoft Graph (Step 3) adapters plug
into. The sub-package itself is layered:

  - `models.py` / `schemas.py` — SQLAlchemy + Pydantic shapes.
  - `oauth.py` — abstract `OAuthProvider` protocol + provider registry.
  - `service.py` — CRUD + the `refresh_if_expired` helper every
    provider's API client calls before issuing a token.
  - `router.py` — admin endpoints (`GET /email/accounts`,
    `DELETE /email/accounts/{id}`). Provider-specific `/connect`
    routes mount under their own sub-routers in Steps 2/3.
  - `module.py` — descriptor with `menu_position=None` (no sidebar
    entry; the Owner manages from Settings → Email Accounts).

Encryption reuses the existing `core.integrations.crypto` module
(same `INTEGRATIONS_ENCRYPTION_KEY` env var) — no parallel infra,
no second key to rotate. Tokens never leave `service.decrypt_tokens`
into a response surface or audit log.
"""
