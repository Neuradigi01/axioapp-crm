# Step 1 — Rename `tbl_embed_keys` → `tbl_api_keys` + add events-scope columns

**Goal:** rename the existing multi-resource embed-keys table, add the columns Track B needs (`auto_create_contacts`, `default_owner_user_id`, `hmac_required`, `mode`, `key_lookup_hash`, `old_key_hash`, `old_key_expires_at`, `hmac_secret_encrypted`, `rate_limit_per_minute`). Extend the `resource_type` CHECK constraint to include `'events'`. Repoint the two existing callers.
**Phase:** Custom Events track — step 1/17
**Depends on:** Step 0 (or verification that dry_run exists)
**Status:** COMPLETED (full original scope — additive columns + table rename)

## Implementation summary

Shipped as two migrations for reviewer-friendly diffs:

- **Migration `0224_api_keys_events_scope`** (additive) — adds 9 events-scope columns (`auto_create_contacts`, `default_owner_user_id`, `hmac_required`, `mode`, `key_lookup_hash`, `old_key_hash`, `old_key_expires_at`, `hmac_secret_encrypted`, `rate_limit_per_minute`) + `ck_embed_keys_mode` CHECK + extends `ck_embed_keys_resource_type` to include `'events'` + partial-unique `ix_embed_keys_lookup_hash`.
- **Migration `0225_rename_embed_to_api_keys`** (rename) — `ALTER TABLE tbl_embed_keys RENAME TO tbl_api_keys` + renames 5 non-PK indexes and both CHECK constraints to `*_api_keys_*`. RLS policy `org_isolation` attached by relation OID — survives the rename automatically (verified by round-trip test).

Model + callers:
- `EmbedKey` class renamed to `ApiKey`; `__tablename__ = "tbl_api_keys"`. `EmbedKey = ApiKey` backward-compat alias kept for one release (retired in Step 2 fold).
- Raw SQL in `core/ai_assistants/janitor.py` updated (`DELETE FROM tbl_api_keys`).
- Test `tests/ai_assistants/test_schema.py::test_embed_keys_extension_backfilled` updated to new table + constraint names.

Config:
- `TRUSTED_PROXIES=` placeholder added to `config.env` for Step 3's XFF chain parsing.

**Secret still to add via `run secrets-edit`** (user runs manually): `HMAC_KEY_PEPPER` — needed by Step 4's HMAC-of-full-key prefilter. Suggested value: `openssl rand -base64 32`.

**PK constraint name cosmetic remnant:** `tbl_embed_keys_pkey` and `tbl_embed_keys_org_id_fkey` still carry their old names (Postgres doesn't auto-rename constraint symbols on `ALTER TABLE RENAME`). Not runtime-critical — they still enforce their invariants. Cleanup deferred to a future housekeeping step if it becomes annoying.

**Secret to add via `run secrets-edit`** (not committed here — user runs manually): `HMAC_KEY_PEPPER` for the Fernet-encrypted HMAC-of-full-key prefilter used by Step 4. Suggested value: `openssl rand -base64 32`.

## Scope

**In-scope:**
- Alembic migration (revision ID ≤ 32 chars):
  1. `ALTER TABLE tbl_embed_keys RENAME TO tbl_api_keys`.
  2. `ALTER SEQUENCE` / rename related indexes/constraints (Alembic autogenerate names them).
  3. Extend `resource_type` CHECK: add `'events'`.
  4. Add columns:
     - `auto_create_contacts BOOLEAN NOT NULL DEFAULT TRUE`.
     - `default_owner_user_id UUID NULL REFERENCES tbl_users(id) ON DELETE SET NULL`.
     - `hmac_required BOOLEAN NOT NULL DEFAULT FALSE` (existing rows keep false — only events keys will default true at create time via service layer).
     - `mode VARCHAR(4) NOT NULL DEFAULT 'live' CHECK (mode IN ('live','test'))`.
     - `key_lookup_hash BYTEA` — HMAC-of-full-key using pepper from `secrets.enc.env` (Fernet-encrypted at rest). Backfilled below.
     - `old_key_hash BYTEA NULL`.
     - `old_key_expires_at TIMESTAMPTZ NULL`.
     - `hmac_secret_encrypted BYTEA NULL` (Fernet-encrypted; NULL for non-events keys).
     - `rate_limit_per_minute INTEGER NOT NULL DEFAULT 100` (events keys). Existing per-hour semantics on `rate_limit_per_hour` preserved for embed/ai_assistant keys.
  5. Add index `CREATE UNIQUE INDEX idx_api_keys_lookup_hash ON tbl_api_keys(key_lookup_hash) WHERE key_lookup_hash IS NOT NULL`.
  6. Backfill `key_lookup_hash` for existing rows using a one-shot Python data migration (compute HMAC-of-key from the Argon2id-hashed key is impossible — instead, mark existing rows for lazy backfill on next verify; new keys populate on create).
- Rename SQLAlchemy model class + table name in `core/embed/models.py`.
- Repoint callers:
  - `core/embed/*` — all references to `tbl_embed_keys` → `tbl_api_keys`.
  - `core/ai_assistants/public_context.py` — same.
  - Tests.
- Add Fernet-encrypted `HMAC_KEY_PEPPER` to `API/secrets.enc.env` (via `run secrets-edit` per project convention; do NOT hand-edit).
- Add config `TRUSTED_PROXIES` (comma-separated list) to `API/config.env`.

**Out of scope:**
- Actual events-endpoint implementation (Step 7).
- Public_ingest module fold (Step 2).
- HMAC-prefilter runtime logic (Step 4).

## Files to touch
- `api/alembic/versions/NNNN_api_keys_extend.py` (new; revision ID ≤ 32 chars, e.g. `NNNN_apikeys_extend`).
- `api/src/app/core/embed/models.py` (modified — class rename `EmbedKey` → `ApiKey`; `__tablename__` update; kept as `core/embed/` file until Step 2 moves it).
- `api/src/app/core/embed/service.py`, `router.py`, `data_access.py` (modified — table refs).
- `api/src/app/core/ai_assistants/public_context.py` (modified).
- `api/src/app/shared/db/__init__.py` or wherever RLS policies are registered (modified — table name).
- `API/config.env` (modified — `TRUSTED_PROXIES=`).
- `API/secrets.enc.env` (modified via `run secrets-edit` — `HMAC_KEY_PEPPER=<fernet-generated>`).
- Tests.

## Plan
1. Write migration (up + down).
2. Model + code rename.
3. Data migration for existing rows: `key_lookup_hash` stays NULL for pre-existing rows; on next Argon2id verify success, service backfills the hash. Documented as one-shot backfill.
4. Add secrets/config.
5. Run `API\run.cmd upgrade` per project memory (all DB ops go through the docker helper).
6. Test embed flow still works.
7. Test ai_assistant public path still works.

## DB changes / migrations
See Scope above. Down migration = reverse everything: drop added columns, rename table back, restore CHECK.

## Tests to add
- `test_api_keys_migration_preserves_embed_hashes` — existing embed keys still verify.
- `test_api_keys_migration_preserves_ai_assistant_scopes`.
- `test_api_keys_new_columns_default_correctly`.
- `test_api_keys_check_constraint_now_allows_events`.
- `test_api_keys_lookup_hash_backfilled_on_verify`.
- `test_api_keys_migration_down_restores_original_shape`.

## Verification checklist
- Backend: migration up + down clean via `API\run.cmd upgrade` and `API\run.cmd downgrade`.
- Backend: `uv run pytest api/tests/test_embed_endpoint.py -x` passes.
- Backend: `uv run pytest api/tests/test_ai_assistants_public.py -x` passes.
- Backend: check `secrets.enc.env` decrypts + `HMAC_KEY_PEPPER` present.
- Backend: `config.env` has `TRUSTED_PROXIES=`.
- Code review: no residual `tbl_embed_keys` references.

## Self-check
- [ ] Rule 1: core only.
- [ ] Rule 2: renamed table keeps org_id + RLS.
- [ ] Rule 8: ~8 files.
- [ ] Rule 10: migration complete; no half-done.
- [ ] Feedback (project memory): revision ID ≤ 32 chars.
- [ ] Feedback (project memory): migration executed via `API\run.cmd upgrade`.

## Stop & report
Await "proceed".
