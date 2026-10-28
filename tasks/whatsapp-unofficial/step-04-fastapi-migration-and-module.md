# Step 4 — FastAPI Alembic migration + module skeleton

**Goal:** Land the FastAPI-side foundation. One Alembic migration that (a) adds `whatsapp_web` to the `integration_provider` PG enum and (b) creates the single new table `tbl_whatsapp_web_sessions`. Drop in the empty `core/integrations/whatsapp_web/` module with the 5-file layered skeleton — no business logic yet, just the shape. Steps 5–7 fill it in.
**Track:** WhatsApp Unofficial (Baileys)
**Status:** Pending
**Depends on:** Step 3 (sidecar feature-complete and reachable for local dev).

---

## Scope

In-scope:

- **Alembic migration `0117_whatsapp_web.py`** (timestamp prefix follows existing convention):
  - `ALTER TYPE integration_provider ADD VALUE IF NOT EXISTS 'whatsapp_web'` — Postgres enum extension. Must run **outside a transaction** (per existing pattern in repo — see migration `0053_whatsapp_provider`). Document the `op.execute(...)` block accordingly.
  - **Create `tbl_whatsapp_web_sessions`** with these columns:
    - `id UUID PK default gen_random_uuid()`
    - `org_id UUID NOT NULL` — `TenantScoped` mixin
    - `integration_id UUID NOT NULL` FK → `tbl_integrations(id) ON DELETE CASCADE`
    - `sidecar_session_id TEXT NOT NULL UNIQUE` — the UUID FastAPI generates and passes to the sidecar
    - `status TEXT NOT NULL DEFAULT 'pending'` — `pending | pairing | connected | reconnecting | disconnected | logged_out | error`. CHECK constraint on the value set.
    - `phone_number TEXT NULL` — populated by the sidecar's `connection.opened` event
    - `last_event_at TIMESTAMPTZ NULL`
    - `last_error TEXT NULL`
    - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
    - `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - **Index**: `(org_id, integration_id)` partial WHERE `status NOT IN ('disconnected','logged_out')` — hot-path lookup.
  - **RLS policy** — match the project pattern (`USING (org_id = current_setting('app.org_id', true)::uuid)`).
  - **Migration is reversible**: `downgrade()` drops the table; the enum value cannot be removed in Postgres so we leave it (documented in the migration file's docstring — same pattern as `0053`).
- **`WhatsAppWebSession` ORM** in `core/integrations/whatsapp_web/models.py`:
  - Standard `Base, TenantScoped` inheritance.
  - SQLAlchemy 2.x `Mapped[...]` columns matching the migration shape.
  - Helpful `__repr__` for debug logs.
- **Empty module skeleton** under `core/integrations/whatsapp_web/`:
  - `__init__.py` — empty.
  - `models.py` — the ORM above.
  - `schemas.py` — Pydantic v2 placeholders: `WhatsAppWebStatus` (enum), `WhatsAppWebSessionOut` (response shape). No request schemas yet — they land in Step 5.
  - `data_access.py` — two functions: `get_session(session, *, integration_id)` and `upsert_session(session, *, integration_id, sidecar_session_id)`. Pure CRUD, no business logic.
  - `service.py` — empty file with the docstring describing the responsibility envelope (no functions yet).
  - `router.py` — empty FastAPI APIRouter with no routes yet — exported so it can be wired into `core/integrations/router.py` later in Step 5.
- **`IntegrationProvider` enum extension** in `core/integrations/models.py` — add `whatsapp_web = "whatsapp_web"` to the Python enum so SQLAlchemy can read the new PG value.
- **Settings additions** in `shared/config.py` (or equivalent — `API/config.py` for the flat-module layout currently in use):
  - `WHATSAPP_WEB_SIDECAR_URL: str = "http://localhost:4000"` — default for local dev.
  - `WHATSAPP_WEB_SIDECAR_HMAC_SECRET: str = ""` — outbound HMAC secret (matches sidecar's `SIDECAR_HMAC_SECRET`).
  - `WHATSAPP_WEB_INBOUND_HMAC_SECRET: str = ""` — inbound HMAC secret (matches sidecar's `FASTAPI_HMAC_SECRET`).
  - Booted: a fail-fast warning at app start when these are empty in non-dev (existing pattern in config.py).
- **`secrets.enc.env` and `config.env`** entries — added via `run secrets-edit` (NOT hand-edited):
  - `WHATSAPP_WEB_SIDECAR_HMAC_SECRET=...` in `secrets.enc.env`
  - `WHATSAPP_WEB_INBOUND_HMAC_SECRET=...` in `secrets.enc.env`
  - `WHATSAPP_WEB_SIDECAR_URL=http://whatsapp-web-sidecar:4000` in `config.env`
- **Module wiring** — `core/integrations/whatsapp_web/router.py` is imported and mounted in `core/integrations/router.py` under `/whatsapp-web`. The mount lands now (empty router); routes themselves are added in Step 5.
- **Tests**:
  - `tests/integrations/test_whatsapp_web_models.py` — ORM imports cleanly, `WhatsAppWebSession.__tablename__ == 'tbl_whatsapp_web_sessions'`.
  - `tests/migrations/test_0117_whatsapp_web.py` — upgrade applies, table exists, RLS policy present, downgrade drops the table cleanly. Reuses the existing migration-test harness.

Out of scope:

- **Connect / disconnect / status endpoints** — Step 5.
- **Sidecar client** — Step 5.
- **Events receiver** — Step 6.
- **Channel adapter** — Step 7.
- **Frontend** — Step 8.

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/0117_whatsapp_web.py` | **NEW** — migration |
| `API/src/app/core/integrations/models.py` | **MODIFY** — add `whatsapp_web` enum value |
| `API/src/app/core/integrations/whatsapp_web/__init__.py` | **NEW** (empty) |
| `API/src/app/core/integrations/whatsapp_web/models.py` | **NEW** — `WhatsAppWebSession` |
| `API/src/app/core/integrations/whatsapp_web/schemas.py` | **NEW** — enum + response Pydantic |
| `API/src/app/core/integrations/whatsapp_web/data_access.py` | **NEW** — 2 CRUD functions |
| `API/src/app/core/integrations/whatsapp_web/service.py` | **NEW** (docstring only) |
| `API/src/app/core/integrations/whatsapp_web/router.py` | **NEW** (empty APIRouter) |
| `API/src/app/core/integrations/router.py` | **MODIFY** — mount `/whatsapp-web` |
| `API/config.py` | **MODIFY** — 3 new env-var-backed constants |
| `API/config.env` | **MODIFY** — add `WHATSAPP_WEB_SIDECAR_URL` |
| `API/secrets.enc.env` | **MODIFY** — add 2 HMAC secrets via `run secrets-edit` |
| `API/tests/integrations/test_whatsapp_web_models.py` | **NEW** |
| `API/tests/migrations/test_0117_whatsapp_web.py` | **NEW** |

**14 files. ~300 lines net.** Within rule-8 budget.

## Plan

1. **Read existing migrations** `0053_whatsapp_provider.py` (enum extension) and `0114_quick_links.py` (RLS-scoped TenantScoped table) to mirror conventions exactly — column ordering, downgrade behaviour, RLS policy SQL string.
2. **Generate migration**: `uv run alembic revision -m "add whatsapp_web provider and sessions table"`. Manually adjust the file:
   - Set `revision = '0117'`, `down_revision = '0116'` (last known migration).
   - `op.execute("ALTER TYPE integration_provider ADD VALUE IF NOT EXISTS 'whatsapp_web'")` — outside transaction.
   - `op.create_table("tbl_whatsapp_web_sessions", ...)` with all columns.
   - `op.create_index(...)` for the partial index.
   - `op.execute("ALTER TABLE tbl_whatsapp_web_sessions ENABLE ROW LEVEL SECURITY")` + `CREATE POLICY ...`.
3. **Write `WhatsAppWebSession` ORM** matching the migration column-for-column.
4. **Write `data_access.py`** with 2 functions:
   ```python
   async def get_session_by_integration(db: AsyncSession, *, integration_id: uuid.UUID) -> WhatsAppWebSession | None: ...
   async def upsert_session(db: AsyncSession, *, integration_id, sidecar_session_id, **patches) -> WhatsAppWebSession: ...
   ```
   No transactions inside DAL (per layered-architecture rule).
5. **Write `schemas.py`**:
   ```python
   class WhatsAppWebStatus(str, Enum):
       pending = "pending"
       pairing = "pairing"
       connected = "connected"
       reconnecting = "reconnecting"
       disconnected = "disconnected"
       logged_out = "logged_out"
       error = "error"

   class WhatsAppWebSessionOut(BaseModel):
       id: UUID
       status: WhatsAppWebStatus
       phone_number: str | None
       last_event_at: datetime | None
       last_error: str | None
       connected_at: datetime | None  # from Integration.connected_at
       model_config = ConfigDict(from_attributes=True)
   ```
6. **`router.py`** — `router = APIRouter(prefix="/whatsapp-web", tags=["integrations:whatsapp-web"])` with no endpoints yet.
7. **`core/integrations/router.py`** — add `from .whatsapp_web.router import router as whatsapp_web_router; router.include_router(whatsapp_web_router)`.
8. **Config additions** — `config.py` reads the 3 env vars with defaults.
9. **Secrets** — `run secrets-edit`, add both 64-char hex secrets:
   ```
   WHATSAPP_WEB_SIDECAR_HMAC_SECRET=<openssl rand -hex 32>
   WHATSAPP_WEB_INBOUND_HMAC_SECRET=<openssl rand -hex 32>
   ```
10. **Tests** — 1 unit (model import + tablename) + 1 migration test (upgrade/downgrade smoke + RLS policy assert).

## DB changes / migrations

**Yes — one migration:**
- `0117_whatsapp_web.py` per the spec above.

**Verify with raw SQL after `uv run alembic upgrade head`:**

```sql
-- enum value present
SELECT enumlabel FROM pg_enum
WHERE enumtypid = 'integration_provider'::regtype;
-- expected: ... whatsapp, whatsapp_web

-- table + columns
\d tbl_whatsapp_web_sessions

-- RLS enabled
SELECT relrowsecurity FROM pg_class
WHERE relname = 'tbl_whatsapp_web_sessions';
-- expected: t

-- policy present
SELECT polname FROM pg_policy
WHERE polrelid = 'tbl_whatsapp_web_sessions'::regclass;
-- expected: at least one row (e.g. tenant_isolation)
```

## Tests

- `test_whatsapp_web_models.py` — 2 cases (import works, tablename is correct).
- `test_0117_whatsapp_web.py` — 3 cases (upgrade succeeds, table+RLS exist, downgrade drops the table).

## Smoke

```
1. Apply migration:
     uv run alembic upgrade head
   Confirm `0117_whatsapp_web` is in `alembic_version`.

2. Check enum and table via psql (queries above).

3. Confirm new env vars load:
     uv run python -c "from config import (
       WHATSAPP_WEB_SIDECAR_URL,
       WHATSAPP_WEB_SIDECAR_HMAC_SECRET,
       WHATSAPP_WEB_INBOUND_HMAC_SECRET,
     ); print(repr(WHATSAPP_WEB_SIDECAR_URL))"
   Should print the configured URL.

4. Start FastAPI:
     run start
   Confirm boot log shows no error from the whatsapp_web module import.
   The empty router mount line should appear in routes (uv run python -c
   "from src.app.main import app; print([r.path for r in app.routes if
   'whatsapp-web' in r.path])") — empty list expected (no endpoints yet).

5. Downgrade smoke:
     uv run alembic downgrade -1
   Confirm `tbl_whatsapp_web_sessions` is dropped (enum value remains,
   that's documented).
   Re-upgrade:
     uv run alembic upgrade head
```

## Risks

- **Enum extension outside transaction.** Existing migration `0053` does this; copy that exact pattern. Forgetting the `op.execute` outside `with op.batch_alter_table` / inside a transactional block causes the migration to fail mid-run on certain Postgres versions.
- **`integration_id` not unique per provider.** Today `Integration` rows are unique per `(org_id, provider)`. A new `Integration` row with `provider=whatsapp_web` coexists with the existing `provider=whatsapp` row for the same org. The new table FKs to integration; deletion cascades cleanly. No constraint conflicts.
- **`tbl_whatsapp_web_sessions.integration_id` FK uniqueness.** One integration row → one session row (UNIQUE on `integration_id`). Multi-session per integration is the same hack pattern as multi-number-per-WABA (Step 27a) — punt to a future track if needed; v1 is one Web number per org.

  **Decision:** Add `UNIQUE(integration_id)` to keep the schema honest. Multi-number Web is a separate track.

- **`sidecar_session_id` collision.** Generated as UUID v4 in FastAPI before posting to sidecar. Probability is astronomical, but the `UNIQUE` index catches it as a 500 → retry with a new UUID (Step 5 handles).
- **RLS policy regression.** Add a smoke query in the migration test that asserts a query without `app.org_id` set returns 0 rows.

## Self-check (10 rules)

- [ ] Rule 1: No `core/` ↔ `packs/` imports. New module is pure core.
- [ ] Rule 2: New table has `org_id` via TenantScoped + RLS policy in migration + `tbl_` prefix. ✅
- [ ] Rule 3: No custom-field work.
- [ ] Rule 4: No dynamic form changes.
- [ ] Rule 5: No sidebar registry change.
- [ ] Rule 6: No new permission keys (reuses `settings.integrations.manage`).
- [ ] Rule 7: `pack.yaml` untouched.
- [ ] Rule 8: 14 files, ~300 lines.
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: No TODOs. Empty `service.py` carries an explicit docstring stating "Step 5 fills in connect / disconnect / status" — it's a scaffold, not a placeholder for forgotten work.

## Stop & report

```
Step 4 — FastAPI Alembic migration + module skeleton

Files changed:
- 1 new migration: alembic/versions/0117_whatsapp_web.py
- 7 new module files under core/integrations/whatsapp_web/
- 2 new tests
- 4 modified: integrations/models.py (enum), integrations/router.py
  (mount), config.py (3 env vars), config.env + secrets.enc.env

What you can verify:
- `uv run alembic upgrade head` applies cleanly
- `tbl_whatsapp_web_sessions` exists with RLS enabled and one policy
- `integration_provider` enum includes `whatsapp_web`
- FastAPI imports the new module without error
- `uv run pytest -k whatsapp_web` passes 2 unit tests + 3 migration tests
- Downgrade -> upgrade is idempotent

Tests added:
- tests/integrations/test_whatsapp_web_models.py (2)
- tests/migrations/test_0117_whatsapp_web.py (3)

Self-check: 10 rules, all green.

Raw INSERT SQL to seed a test row (paste in psql with app.org_id set):
  SET LOCAL app.org_id = '<org-uuid>';
  INSERT INTO tbl_whatsapp_web_sessions (
    org_id, integration_id, sidecar_session_id, status
  ) VALUES (
    current_setting('app.org_id')::uuid,
    '<integration-uuid>',
    gen_random_uuid()::text,
    'pending'
  );

Next: Step 5 — implement connect / disconnect / status endpoints +
HMAC-signed sidecar HTTP client.

Awaiting your "proceed".
```
