# Step 1.2 — Backend bootstrap

**Goal:** Bring up a runnable FastAPI app at the new layered package root with health endpoint, env-based config, structured logging, and a docker-compose stack (Postgres 17 + Redis).
**Phase:** 1
**Depends on:** 1.1
**Status:** Completed

## Scope
**In-scope:**
- New `api/src/app/main.py` FastAPI app instance, mounted at `/api/v1`.
- `api/src/app/shared/config.py` using `pydantic-settings` (env-based; reads `.env`).
- `api/src/app/shared/logging.py` (structured JSON logs via stdlib `logging` + `json` formatter — keep it simple, no extra deps).
- `api/src/app/shared/exceptions.py` (base `AppError` + handler).
- `api/src/app/core/health/router.py` exposing `GET /api/v1/health` returning `{"status":"ok","version":"0.1.0"}`.
- `api/pyproject.toml` written for **uv** with locked stack (FastAPI, uvicorn[standard], pydantic v2, pydantic-settings, sqlalchemy[asyncio], asyncpg, alembic, celery, redis, python-jose, passlib[bcrypt], pyotp, qrcode — all latest compatible).
- `api/uv.lock` generated.
- `api/docker-compose.yml` (dev) with services: `db` (postgres:17), `redis` (redis:7), `api` (build from local Dockerfile, mounts `api/`, runs `uvicorn src.app.main:app --reload`).
- `api/Dockerfile` (slim Python 3.13-bookworm base, uv-installed deps).
- Decision documented: existing `api/src/` retained for now; new code under `api/src/app/`. Auth migration into `app/core/auth/` happens in 1.5/1.6.

**Out of scope:**
- DB connection / Alembic / models — those land in 1.3.
- Auth — 1.6.
- Frontend — 1.9.

## Files to touch
- `api/src/app/main.py` (created)
- `api/src/app/shared/config.py` (created)
- `api/src/app/shared/logging.py` (created)
- `api/src/app/shared/exceptions.py` (created)
- `api/src/app/core/health/__init__.py` (created)
- `api/src/app/core/health/router.py` (created)
- `api/pyproject.toml` (replaced)
- `api/uv.lock` (created)
- `api/Dockerfile` (replaced)
- `api/docker-compose.yml` (replaced)
- `api/.env.example` (created)
- `api/.dockerignore` (created)

## Plan
1. Write `api/pyproject.toml` with locked deps and Python 3.13 requirement; if 3.13 blocks a critical dep, fall back to 3.12 and document which dep forced it.
2. `cd api && uv lock && uv sync` to populate the venv and lock file.
3. Implement `Settings` in `shared/config.py` reading `APP_ENV`, `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `JWT_ALGORITHM` (default `HS256`), `LOG_LEVEL`.
4. Implement structured logger in `shared/logging.py`: JSON formatter, request ID via contextvar, configured at startup.
5. Implement `AppError` base + a global FastAPI exception handler that returns JSON.
6. Build the health router and register it in `main.py`. Add CORS middleware (open in dev).
7. Write Dockerfile (Python 3.13-slim, install uv, copy `pyproject.toml`+`uv.lock`, sync, copy app, run uvicorn).
8. Write docker-compose with `db` (volume `pgdata:/var/lib/postgresql/data`, password from env), `redis`, `api` (depends_on db+redis).
9. Write `.env.example`: `APP_ENV=dev`, `DATABASE_URL=postgresql+asyncpg://crm:crm@db:5432/crm`, `REDIS_URL=redis://redis:6379/0`, `JWT_SECRET=change-me`, `LOG_LEVEL=INFO`.

## DB changes / migrations
None this step.

## Tests to add
- `api/tests/test_health.py` — boots the app via `httpx.AsyncClient` against the ASGI app, hits `GET /api/v1/health`, asserts 200 + `status=ok`.

## Verification checklist
**Backend:**
- run: `cd api && uv run uvicorn src.app.main:app --reload`
- visit: `http://localhost:8000/api/v1/health` → `{"status":"ok","version":"0.1.0"}`
- visit: `http://localhost:8000/docs` → Swagger UI loads.
- run: `docker compose -f api/docker-compose.yml up -d db redis` → both services Up, expose 5432/6379.
- run: `docker compose -f api/docker-compose.yml up api` → starts and binds 8000.

**Code review:**
- open `api/pyproject.toml` — note Python 3.13, locked deps, no v1 Pydantic patterns.
- open `api/src/app/shared/config.py` — uses `BaseSettings` from `pydantic-settings`, not `pydantic`.
- open `api/src/app/main.py` — minimal, just app+router+exception handler+CORS.

## Self-check (10 rules)
- [ ] `app/core/` does not import from `app/packs/`.
- [ ] No DB tables added (rule 2 N/A).
- [ ] No TODOs / placeholders / commented code.
- [ ] Step touched ≤ ~10 files.

## Stop & report
Use the master-prompt stop template; await "proceed" before Step 1.3.