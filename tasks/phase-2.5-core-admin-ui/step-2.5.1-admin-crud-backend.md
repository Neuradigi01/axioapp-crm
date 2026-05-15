# Step 2.5.1 — Backend admin CRUD endpoints

**Goal:** Add the missing CRUD endpoints the admin UI binds against. `GET /users` and `GET /audit` already exist; the rest are missing.
**Phase:** 2.5 — Core CRM Admin UI
**Status:** Pending

---

## Scope

Six endpoints under `/api/v1/`, all gated on the existing permission keys.

| Endpoint | Permission | Behaviour |
|---|---|---|
| `POST /users` | `users.write` | Create a user in the caller's org. Body: `{email, full_name (split to first+last), phone, role_id}`. Writes one row to each of `tbl_user_login`, `tbl_user_info`, `tbl_organization_members`. **Password is not set here** — initial login uses the invite flow (2.5.6). For now, sets a random password the user can never use; UI shows "Send invitation" as the next step. |
| `PATCH /users/{user_id}` | `users.write` | Update a user's `full_name`, `phone`, or `role_id`. `email` is immutable after creation (changing email = invite a new user). Writes to `tbl_user_info` for name/phone, `tbl_organization_members` for role. |
| `PATCH /users/{user_id}/status` | `users.write` | Toggle `tbl_user_login.is_active` and `tbl_organization_members.is_active`. Deactivating revokes all open `auth_sessions` for that user. |
| `POST /roles` | `roles.write` | Create a custom role in the caller's org. Body: `{name, permission_keys: [str]}`. Writes one row to `roles` and N to `role_permissions`. |
| `PATCH /roles/{role_id}` | `roles.write` | Rename a role and/or replace its permission grants. Forbidden on `is_system=true` rows (Admin/Owner/Employee). |
| `DELETE /roles/{role_id}` | `roles.write` | Delete a role. Forbidden if any active membership references it (returns 409 with the count). Forbidden if `is_system=true`. |

Plus two read endpoints to populate dropdowns / matrices:

| Endpoint | Permission | Behaviour |
|---|---|---|
| `GET /roles` | `roles.read` | List roles in the caller's org with permission key counts. |
| `GET /permissions` | `roles.read` | List the global permission registry (all keys + descriptions + module). |

## Why no schema migration

Every column the admin UI mutates already exists (we just split things to 3 tables in DR.7). The `users.id` admin UI surfaces is `user.legacy_uuid` — unchanged from DR.6.4.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/users/router.py` | add `POST /users`, `PATCH /users/{id}`, `PATCH /users/{id}/status` |
| `api/src/app/core/users/service.py` | add `create_user(...)`, `update_user(...)`, `set_user_status(...)` |
| `api/src/app/core/users/schemas.py` | add `UserCreate`, `UserUpdate`, `UserStatusUpdate` |
| `api/src/app/core/permissions/router.py` | add `POST /roles`, `PATCH /roles/{id}`, `DELETE /roles/{id}`, `GET /roles`, `GET /permissions` |
| `api/src/app/core/permissions/service.py` | add `create_role(...)`, `update_role(...)`, `delete_role(...)`, `list_roles_in_org(...)`, `list_permissions()` |
| `api/src/app/core/permissions/schemas.py` | add `RoleCreate`, `RoleUpdate`, `RoleOut`, `PermissionOut` |

**6 files. No migrations. No new tables.**

## Tests

`tests/test_phase_2_5_admin_crud.py`:
- Create user as Admin → 201, returns row with new UUID; row visible in tbl_user_login + tbl_user_info + tbl_organization_members.
- Create user as Employee → 403.
- Update user's role_id → membership row updated; subsequent `/users/me` reflects new role+perms.
- Deactivate user → `is_active=false`, open auth_sessions revoked.
- Create custom role with 2 permission keys → row in roles + 2 rows in role_permissions.
- Delete role with active memberships → 409.
- Delete system role → 403.

## Smoke

```
.\docker-helper.cmd upgrade  # no-op, no migrations
# unit tests:
docker compose ... exec api pytest tests/test_phase_2_5_admin_crud.py -v
# manual curl as admin@core-demo.local:
POST /users { ... } → 201
GET /roles → 3 entries
GET /permissions → ~50 entries
```

## Rollback

Revert the 6 files. No DB state change.
