# Step 2.5.5 — Self-service profile page

**Goal:** Build `/user/profile` — every logged-in user can edit their own name, phone, and password (regardless of role).
**Phase:** 2.5 — Core CRM Admin UI
**Status:** COMPLETED
**Depends on:** Phase 2 `users` module + the existing layered auth.

---

## Scope

One Angular page + one form. Two backend endpoints to add — both keyed off the **current user** (no permission key needed beyond being authenticated):

| Endpoint | Behaviour |
|---|---|
| `PATCH /api/v1/users/me` | Update `tbl_user_info.first_name`, `last_name`, `mobile_no` for the calling user. Email is immutable (changing email = invite a new account; see 2.5.6). |
| `POST /api/v1/users/me/password` | Body: `{current_password, new_password}`. Verifies current, hashes new, writes to `tbl_user_login.password`. Revokes other open `auth_sessions` for this user (keep the current session). |

## UI

```
Profile
─────────
  First name:  [Core Demo]
  Last name:   [Admin]
  Email:       [admin@core-demo.local]   (read-only)
  Phone:       [+91 9876543210]

  [Save]

Password
─────────
  Current password:  [********]
  New password:      [********]
  Confirm:           [********]
  ☐ Sign out of all other sessions

  [Change password]
```

Two independent sub-forms with their own submit buttons.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/users/router.py` | add `PATCH /me`, `POST /me/password` |
| `api/src/app/core/users/service.py` | add `update_self(...)`, `change_password(...)` |
| `api/src/app/core/users/schemas.py` | add `MeUpdate`, `PasswordChange` |
| `app/src/app/features/user/core/profile/profile-page.component.ts` | created |
| `app/src/app/features/user/core/profile/profile-page.component.html` | created |
| `app/src/app/features/user/core/profile/profile.service.ts` | created |
| `app/src/app/features/user/user.routes.ts` | register `/profile` route |

**~7 files.**

## Password change details

- Use the existing `verify_password` + `hash_password` helpers (`src/app/shared/security/password.py`).
- On success, write `auth_logs` audit row `auth.password.changed` (action key already exists / register if not).
- If `Sign out of all other sessions` is checked → set `auth_sessions.revoked_at = now()` for every row of the current user *except* the current `token_id` from the JWT.

## Smoke

```
ng build --configuration development  # clean
# In browser as admin@core-demo.local:
#   - Click avatar → "Profile" → /user/profile
#   - Change phone → save → toast success → /me reflects it
#   - Change password (current=Admin@123 → new=NewAdmin@456) → success
#   - Log out, log in with NewAdmin@456 → works
#   - Open a second browser tab, log in. Change password again with "Sign out other sessions" ticked.
#     The second tab's next API call returns 401.
```

## Rollback

Revert the backend trio + delete the 4 frontend files. No DB schema change.
