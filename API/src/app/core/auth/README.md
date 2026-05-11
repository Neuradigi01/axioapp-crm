# Auth — Token shape and lifecycle

This module owns FurnitureCRM's JWT-based admin auth. It is built on
top of the layered RBAC (`users`, `roles`, `permissions`) introduced
in Step 1.5. The legacy template's auth pages keep working unchanged
until the frontend is migrated; this is the canonical backend path
for everything under `/api/v1/...`.

## Token shape

A successful login returns a single JWT, signed with HS256 using
`JWT_SECRET_KEY` from `.env`. The token doubles as both access and
refresh credential — there is no separate refresh token. The
`auth_sessions` table makes per-token revocation possible despite the
JWT being stateless.

### Claims

| claim      | type          | meaning                                                          |
|------------|---------------|------------------------------------------------------------------|
| `sub`      | UUID string   | The `users.id` the token authenticates.                          |
| `org_id`   | UUID string   | Tenant the user belongs to. Becomes `RequestContext.org_id`.     |
| `token_id` | UUID string   | PK of the matching `auth_sessions` row. Becomes `RequestContext.token_id`. |
| `iat`      | int (epoch s) | Issued at.                                                       |
| `exp`      | int (epoch s) | Expiry. Default TTL is 24h (`tokens.ACCESS_TOKEN_TTL`).          |

The `org_id` claim is what feeds Row-Level Security: the
`TenantContextMiddleware` decodes the JWT, pushes `org_id` into the
contextvar, and the DB session lifecycle hook in
`src.app.shared.db` issues `set_config('app.org_id', ...)` for the
transaction.

## Endpoints

All under `/api/v1/auth/`:

### `POST /login`

```json
{ "email": "admin@demo.local", "password": "Admin@123", "org_slug": "demo" }
```

Returns:

```json
{
  "access_token": "<jwt>",
  "token_type": "Bearer",
  "expires_at": "2026-05-12T10:23:11.123456+00:00"
}
```

Rate-limited to **10 attempts per minute per IP**
(in-memory token bucket from `src.app.shared.rate_limit.login_limiter`).
The 11th request inside the same window returns 429 with a
`Retry-After` header.

Failure modes:

- Unknown org slug, unknown email, inactive user, or wrong password
  all return the same 401 (`Invalid credentials`) to prevent
  enumeration.

### `POST /refresh`

Pass the current valid JWT in the `Authorization: Bearer <jwt>`
header. The server revokes that session (`auth_sessions.revoked_at`)
and issues a brand-new JWT with a fresh `token_id`. The old token is
permanently dead from that moment.

### `POST /logout`

Same auth requirement as refresh. Sets `revoked_at` on the current
session row. Idempotent — already-revoked tokens silently return 200.
Subsequent requests with the old token fail at
`get_current_user` with 401.

## Session revocation

`auth_sessions` is tenant-scoped (RLS-enforced) so revocation
operations naturally honour tenant boundaries. The `get_current_user`
dependency checks the matching `auth_sessions` row on every protected
request; a row that is missing, revoked, or past `expires_at` results
in 401 even if the JWT signature is still valid.

## Permissions check

For routes that need permission gating use
`Depends(require_permissions("users.write", "..."))`. Composes on top
of `get_current_user` and loads the user's role's permission keys.
The admin role seeded by `seed_admin_user` has all four keys.

## Dev shortcut

In development (when `IS_DEVELOPMENT=true` in `.env`), the middleware
also accepts `X-Org-Id` and `X-User-Id` headers as a fallback when no
`Authorization` header is sent. This is how the test suite drives
context without minting JWTs and how a developer can hit `/users/me`
from curl during local exploration. In production these headers are
ignored.
