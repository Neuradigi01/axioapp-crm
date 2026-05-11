# Step 1.6 — Auth (JWT) for admin login

**Goal:** Move the existing JWT login flow into `app/core/auth/`, issue tokens that carry `org_id` + `user_id` + `token_id`, replace the dev `X-User-Id` / `X-Org-Id` placeholder with real JWT extraction in middleware, add login rate limiting.
**Phase:** 1
**Depends on:** 1.5
**Status:** Pending

## Scope
**In-scope:**
- New layered auth modules under `app/core/auth/`:
  - `service.py` — login (verify password + issue token), refresh, logout (invalidate token_id).
  - `router.py` — `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`, `POST /api/v1/auth/logout`.
  - `dependencies.py` — `get_current_user`, `require_permissions(...)` dependencies.
  - `tokens.py` — JWT encode/decode (HS256 from settings) with `org_id`, `user_id`, `token_id` claims.
  - `schemas.py` — `LoginRequest`, `LoginResponse`, `RefreshRequest`.
- Token blacklist / session table `auth_sessions` (id=token_id, user_id, org_id, created_at, expires_at, revoked_at) for invalidation. `TenantScoped`, RLS-enabled.
- Migration `0004_auth_sessions.py`.
- Update `TenantContextMiddleware` to extract `org_id`+`user_id`+`token_id` from `Authorization: Bearer <jwt>` and remove the `X-Org-Id`/`X-User-Id` dev shortcut. (Keep the dev shortcut behind `APP_ENV=dev` flag for tests.)
- `GET /api/v1/users/me` now requires a valid token.
- Login rate limiting: simple in-memory + Redis-backed limiter (e.g. `slowapi` or hand-rolled token bucket on Redis) — 10 attempts/min/IP.
- Decision: 2FA flows (Google Auth, Email OTP, SMS OTP) re-housed too OR deferred to a later "Auth-2FA-port" sub-step. Default: defer to Phase 1.6b sub-step OR fold into 1.6 if it fits the size budget. (Adjust at execution time; if 2FA push exceeds the size budget, split into 1.6a/1.6b.)
- Document token shape in `api/app/core/auth/README.md`.

**Out of scope:**
- Audit logs hookup — 1.7.
- Module registry — 1.8.
- Frontend wire-up — 1.9.

## Files to touch
- `api/app/core/auth/__init__.py` (created)
- `api/app/core/auth/router.py` (created)
- `api/app/core/auth/service.py` (created)
- `api/app/core/auth/dependencies.py` (created)
- `api/app/core/auth/tokens.py` (created)
- `api/app/core/auth/schemas.py` (created)
- `api/app/core/auth/models.py` (created — `AuthSession`)
- `api/app/core/auth/README.md` (created — token shape doc)
- `api/app/shared/middleware.py` (modified — JWT extraction)
- `api/app/shared/rate_limit.py` (created — Redis token bucket)
- `api/alembic/versions/0004_auth_sessions.py` (created)
- `api/app/main.py` (modified — register auth router)
- Updated `users/router.py` to use `Depends(get_current_user)`.

## Plan
1. Implement `tokens.py`: encode `{sub: user_id, org_id, token_id, exp, iat}`; decode with verification. JWT_SECRET + algorithm from settings.
2. Implement `AuthSession` model + migration (token_id PK, indexed by user_id and expires_at).
3. Implement `service.login(email, password, ip, ua)`: lookup user by email + org context (org resolved by email-domain mapping or a `?org_slug=` query param — DEFAULT decision: include `org_slug` in login request body), verify password, create `AuthSession`, return JWT.
4. Implement `service.refresh(refresh_token)`: rotate token_id, revoke old, issue new.
5. Implement `service.logout(token_id)`: set `revoked_at`.
6. Update middleware: parse `Authorization: Bearer <jwt>`, decode, check `AuthSession` not revoked, set `RequestContext`. On failure → 401.
7. Implement `get_current_user` dependency that reads from RequestContext.
8. Implement Redis token-bucket limiter; attach to `/auth/login` (10/min/IP).
9. Document token shape in `core/auth/README.md` (claims, lifetime, refresh flow).
10. Update `users/router.py:GET /users/me` to require `Depends(get_current_user)`.

## DB changes / migrations
- Migration `0004_auth_sessions`: `auth_sessions(id uuid PK = token_id, org_id uuid FK, user_id uuid FK→users, created_at, expires_at, revoked_at, ip text, ua text)` + RLS + indexes.

## Tests to add
- `tests/test_auth_login.py` — login with correct creds → 200 + token; wrong → 401.
- `tests/test_auth_me.py` — `/users/me` with valid token → 200; without → 401; with revoked token → 401.
- `tests/test_auth_refresh.py` — refresh rotates token_id; old token rejected.
- `tests/test_auth_rate_limit.py` — 11th attempt within a minute → 429.

## Verification checklist
**Backend:**
- hit: `curl -X POST localhost:8000/api/v1/auth/login -d '{"email":"admin@demo.local","password":"Admin@123","org_slug":"demo"}'` → 200 + `access_token`.
- hit: `curl localhost:8000/api/v1/users/me -H 'Authorization: Bearer <token>'` → 200 + user JSON.
- hit: 11 rapid logins → last one 429.
- run: `uv run pytest -q` → green.

**Code review:**
- open `api/app/core/auth/README.md` — token claims documented.
- open `api/app/shared/middleware.py` — note JWT-only path; dev shortcut gated behind `APP_ENV=dev`.

## Self-check (10 rules)
- [ ] `org_id` on `auth_sessions` + RLS.
- [ ] Step ≤ ~13 files (split into 1.6a/1.6b if 2FA migration pushes it over).
- [ ] No TODOs.

## Stop & report
Use the master-prompt stop template; await "proceed" before Step 1.7.
