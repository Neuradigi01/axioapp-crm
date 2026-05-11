# Phase 1 — Foundation & Scaffolding

**Goal:** Stand up the empty house — backend skeleton, database, JWT auth, multi-tenancy primitives, module registry, frontend bootstrap, app shell. Nothing functional yet, but a user can log in and see an empty dashboard with a sidebar driven by the module registry.

**Phase completion criteria:** A user can log in, see the shell, sidebar is rendered from the module registry, `GET /api/v1/users/me` works, audit logs are written. Code is clean, tests pass.

## Steps

| # | Title | Status |
|---|-------|--------|
| 1.1 | [Repository skeleton](step-1.1-repo-skeleton.md) | Pending |
| 1.2 | [Backend bootstrap](step-1.2-backend-bootstrap.md) | Pending |
| 1.3 | [Database connection & Alembic](step-1.3-db-alembic.md) | Pending |
| 1.4 | [Multi-tenancy primitives](step-1.4-multi-tenancy.md) | Pending |
| 1.5 | [Users, Roles, Permissions](step-1.5-users-roles-permissions.md) | Pending |
| 1.6 | [Auth (JWT) for admin login](step-1.6-auth-jwt.md) | Pending |
| 1.7 | [Audit logs](step-1.7-audit-logs.md) | Pending |
| 1.8 | [Module registry (backend)](step-1.8-module-registry.md) | Pending |
| 1.9 | [Frontend bootstrap (Angular)](step-1.9-frontend-bootstrap.md) | Pending |
| 1.10 | [App shell (sidebar + header)](step-1.10-app-shell.md) | Pending |

## Dependencies

- Step 1.1 must complete first (sets repo layout for everything else).
- 1.2 depends on 1.1.
- 1.3 depends on 1.2.
- 1.4 depends on 1.3.
- 1.5 depends on 1.4 (uses tenancy mixin).
- 1.6 depends on 1.5 (needs users + roles).
- 1.7 depends on 1.5 (needs users) and 1.6 (hooks login flow).
- 1.8 depends on 1.6 (registry endpoint requires auth).
- 1.9 depends on 1.6 (needs login endpoint to call).
- 1.10 depends on 1.8 + 1.9 (renders modules from registry endpoint).
