# Step 1 — BYOK provider-key store (`core/integrations/ai/`)

**Goal:** Land the org-scoped, encrypted OpenAI key store as a sub-module of `core/integrations/`. AES-GCM with a dedicated KEK + AAD binding, SHA-256 fingerprint dedup, rate-limited test endpoint, and an org-level daily/monthly USD budget cap ledger. No LLM adapter yet (Step 2) and no UI yet (Step 3).
**Status:** Pending
**Depends on:** `core/integrations/` exists (it does); Fernet infrastructure in [API/src/app/core/integrations/crypto.py](API/src/app/core/integrations/crypto.py) exists as reference.

---

## Scope

In-scope:

- Migration `<ts>_ai_provider_keys.py` — two tables + one ENUM + RLS + indexes.
  - `tbl_ai_provider_keys`:
    - `id`, `org_id`, `provider` ENUM (`openai` only in v1; `anthropic` / `google` / `openrouter` reserved), `label` text (default `"Default"`), `encrypted_key` bytea (AES-GCM ciphertext), `nonce` bytea, `key_version` int default 1 (part of AAD; enables future re-encrypt), `fingerprint_sha256` bytea (32 bytes; enables dedup + cross-org copy detection), `last4` text, `test_status` ENUM (`untested` / `success` / `failed`) default `untested`, `test_last_at` timestamp nullable, `test_last_error` text nullable, `revoked_at` timestamp nullable, audit cols. Unique `(org_id, provider, fingerprint_sha256)` — prevents duplicate key material in same org. Index `(org_id, provider, revoked_at)`.
  - `tbl_org_ai_cost_budget`:
    - `id`, `org_id` UNIQUE, `daily_cap_usd` numeric(10,4) default `10.00`, `monthly_cap_usd` numeric(10,4) default `200.00`, `spent_today_usd` numeric(10,4) default 0, `spent_month_usd` numeric(10,4) default 0, `day_bucket` date, `month_bucket` text (`YYYY-MM`), audit cols.
- SQLAlchemy models in `core/integrations/ai/models.py` — `AiProviderKey`, `OrgAiCostBudget`, both `TenantScoped`.
- Pydantic schemas in `core/integrations/ai/schemas.py` — `AiProviderKeyCreate` (accepts `provider`, `label`, `api_key` **plaintext**; **rejects** `base_url`, `organization`, `custom_headers`, `id`, `org_id`, `fingerprint_sha256`, `encrypted_key`, `nonce`, `revoked_at`), `AiProviderKeyRead` (returns masked last-4 only), `AiProviderKeyReassign` (`from_key_id`, `to_key_id`), `OrgAiCostBudgetRead`, `OrgAiCostBudgetUpdate`.
- Service in `core/integrations/ai/service.py`:
  - `create_provider_key(db, org_id, payload)` — dedicated KEK read from `AI_PROVIDER_KEY_KEK` env (via `settings`), AES-GCM encrypt with AAD `f"{org_id}:{key_id_uuid_str}:{key_version}"`, compute fingerprint = `sha256(api_key.encode())`, dedup check via unique constraint (returns 409 with existing row's `id` on collision).
  - `test_provider_key(db, org_id, key_id)` — decrypts, calls `shared.llm.factory('openai', key_id=key_id).probe()` (introduced in Step 2 as a stub returning success/failure); updates `test_status` + `test_last_at`. Rate-limited per user (5/min, 30/day) via a small in-service `_test_rate_limiter` dict keyed on `user_id` with expiry.
  - `delete_provider_key(db, org_id, key_id)` — checks assistant references (via `AiAssistantRepo.count_by_key_id` — introduced in Step 5; for Step 1 the check is a stub that returns 0). Blocks with 409 + list when count > 0.
  - `reassign_provider_key(db, org_id, from_key_id, to_key_id)` — validates both belong to org, updates all `tbl_ai_assistants.key_id` FKs in one transaction (via a bulk UPDATE stubbed until Step 5 — in Step 1 the call raises `NotImplementedError` with a note pointing to Step 5). Step 5 wires the actual UPDATE.
  - `get_or_create_budget(db, org_id)` — idempotent creation; returns budget row.
  - `charge_budget(db, org_id, cost_usd)` — advisory helper called by chat runtime (Step 9); rolls day/month buckets when date changes. Returns `(allowed: bool, reason: str | None)` — false with `daily_cap_hit` / `monthly_cap_hit`.
- Router in `core/integrations/ai/router.py` — JWT-guarded, permission `ai_providers.manage`:
  - `POST /integrations/ai/providers` — create key.
  - `GET /integrations/ai/providers` — list (masked).
  - `POST /integrations/ai/providers/{id}/test` — rate-limited.
  - `POST /integrations/ai/providers/reassign` — reassign.
  - `DELETE /integrations/ai/providers/{id}` — delete (blocked if referenced).
  - `GET /integrations/ai/budget` — read budget.
  - `PATCH /integrations/ai/budget` — update caps.
- Data access in `core/integrations/ai/data_access.py` — pure CRUD.
- Permissions in `core/integrations/ai/permissions.py` — new key `ai_providers.manage`, default Owner+Admin, registered via existing permission registry.
- Startup pin-test in [API/tests/test_ai_provider_kek_isolation.py](API/tests/test_ai_provider_kek_isolation.py) — asserts `AI_PROVIDER_KEY_KEK` env var is set, is 32 bytes base64-decoded, and is **not equal** to `INTEGRATIONS_ENCRYPTION_KEY` / `SIGNED_URL_KEY` / `SECRET_KEY`.
- Config: add `AI_PROVIDER_KEY_KEK` to `API/config.env.example` (documented as base64-32-byte, generate via `python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`). Actual secret goes into `API/secrets.enc.env` via `run secrets-edit`.

Out of scope:
- LLM adapter (Step 2).
- Any UI (Step 3).
- Cross-module bulk-UPDATE of assistant references (Step 5 wires it — Step 1 stubs with `NotImplementedError`).
- pgvector (Step 4).

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_ai_provider_keys.py` | **NEW** |
| `API/src/app/core/integrations/ai/__init__.py` | **NEW** |
| `API/src/app/core/integrations/ai/models.py` | **NEW** |
| `API/src/app/core/integrations/ai/schemas.py` | **NEW** |
| `API/src/app/core/integrations/ai/router.py` | **NEW** |
| `API/src/app/core/integrations/ai/service.py` | **NEW** |
| `API/src/app/core/integrations/ai/data_access.py` | **NEW** |
| `API/src/app/core/integrations/ai/crypto.py` | **NEW** — AES-GCM/AAD wrapper distinct from `core/integrations/crypto.py` |
| `API/src/app/core/integrations/ai/permissions.py` | **NEW** — registers `ai_providers.manage` |
| `API/src/app/main.py` | **EDIT** — side-effect import of `core.integrations.ai.models`; register router |
| `API/src/app/shared/config.py` | **EDIT** — read `AI_PROVIDER_KEY_KEK` env var |
| `API/config.env.example` | **EDIT** — document new env var |
| `API/tests/integrations/ai/test_provider_keys.py` | **NEW** |
| `API/tests/test_ai_provider_kek_isolation.py` | **NEW** — startup pin-test |

**~14 files. ~550 lines.** Slightly over — justified because two tables + AES-GCM/AAD wrapper + KEK isolation test + budget-cap ledger all need to land together for later steps to build on. Splitting the KEK/AAD from the tables would leave a half-built encryption layer for Step 2 to work around.

## Plan

1. Migration first — two tables, one ENUM, RLS policies (`current_setting('app.current_org_id')` gate), indexes.
2. `crypto.py` — thin wrapper around `cryptography.hazmat.primitives.ciphers.aead.AESGCM`: `encrypt(plaintext, aad) -> (ciphertext, nonce)`, `decrypt(ciphertext, nonce, aad) -> plaintext`. Fails hard on any AAD mismatch (surfaces `InvalidTag` as a typed `AADMismatchError`).
3. Models + Pydantic — write schemas strictly whitelist input fields; read schemas expose only `last4` never `encrypted_key`.
4. Service — dedup path uses the unique constraint (`IntegrityError` → 409 with the existing row's masked `last4`); test rate limiter is a simple `defaultdict(deque)` cleaned by TTL.
5. Router — permission `ai_providers.manage` required; all responses use `AiProviderKeyRead` (never leak `encrypted_key` / `fingerprint_sha256`).
6. Pin-test — imports `settings`, asserts `settings.AI_PROVIDER_KEY_KEK` is set, right length, and ≠ any other secret. Runs in CI as any other pytest.

## DB changes / migrations

Two new tables, one new ENUM (`ai_provider`). Reversible (downgrade drops tables then enum).

## Tests

- AES-GCM round-trip: encrypt→decrypt returns original.
- AAD tamper: decrypt with wrong `org_id` in AAD raises `AADMismatchError`.
- Fingerprint dedup: second `POST` with same key material returns 409 + existing `last4`.
- Test endpoint rate limit: 6th call within 60s returns 429.
- Test endpoint failure does not persist: invalid key → `test_status='failed'`, no `encrypted_key` written.
- Cross-org isolation: key from org A invisible in org B's list.
- Delete blocked when reference-count stub returns > 0 (mock the stub).
- KEK-isolation startup pin-test: raises when `AI_PROVIDER_KEY_KEK` unset or equal to another key.
- Budget: `charge_budget` rolls day bucket on date change; monthly cap hit returns `(False, 'monthly_cap_hit')`.
- Mass-assignment: POST with body `{"api_key":"sk-...","org_id":"<other>","id":"<forged>"}` — response's `id` is server-generated; `org_id` is caller's, not the body's.

## Smoke

```
1. Set AI_PROVIDER_KEY_KEK in env (base64 32-byte). run.cmd upgrade.
2. \dt tbl_ai_provider_keys / tbl_org_ai_cost_budget — visible.
3. curl POST /integrations/ai/providers with {"provider":"openai","label":"Default","api_key":"sk-test-invalid"}
   → 201 with masked last4.
4. curl POST /integrations/ai/providers/{id}/test → test_status='failed'.
5. curl POST same key again → 409.
6. curl DELETE {id} → 204 (no assistants yet — stub returns 0).
```

## Risks

- If the operator forgets `AI_PROVIDER_KEY_KEK` in env, the app fails to start (by design — the pin-test enforces this).
- KEK rotation is a future concern; `key_version` on the row supports re-encrypt but the rotation job isn't in this step.
- The reassign stub deliberately raises until Step 5 wires it — dev environment could hit this if a user tries to reassign before Step 5 lands.

## Self-check (10 rules)

`core/integrations/ai/`, no packs. ✓ `org_id` + RLS on both tables + unique-by-fingerprint. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar (surfaces in Settings, Step 3). ✓ Registers `ai_providers.manage` permission. ✓ pack.yaml untouched. ✓ 14 files / ~550 lines — over but justified. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 1 — BYOK provider-key store (core/integrations/ai/)
Files: 14
Verify: KEK-isolation pin-test passes; dedup + rate-limit + AAD-tamper tests pass;
        POST/GET/DELETE flows work; budget roll works.
Tests: ~15 pytest cases.
Awaiting "proceed".
```
