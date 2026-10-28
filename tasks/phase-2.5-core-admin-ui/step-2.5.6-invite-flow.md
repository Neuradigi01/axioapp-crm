# Step 2.5.6 — Invite-user flow

**Goal:** Admin clicks "Invite" → recipient receives an email with a one-time link → recipient sets their password → first login → lands at `/user/dashboard`.
**Phase:** 2.5 — Core CRM Admin UI
**Status:** Pending
**Depends on:** 2.5.1 (POST /users), 2.5.2 (users page), Phase 1 email-sending plumbing if any.

---

## Scope

The biggest single step in 2.5 — it touches schema, backend, and two distinct frontend pages (admin's invite modal + recipient's accept page). Roughly 1.5 days.

## Schema — one new table

```sql
CREATE TABLE invitations (
  id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID         NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
  email           CITEXT       NOT NULL,
  role_id         UUID         NOT NULL REFERENCES roles(id)         ON DELETE RESTRICT,
  invited_by      UUID         NOT NULL,    -- user.legacy_uuid
  token_hash      VARCHAR(255) NOT NULL,    -- bcrypt of the random opaque token
  expires_at      TIMESTAMPTZ  NOT NULL,    -- 7 days from issuance
  accepted_at     TIMESTAMPTZ  NULL,        -- non-null = redeemed
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_invitations_org_id_email ON invitations (org_id, email);
CREATE INDEX ix_invitations_token_hash   ON invitations (token_hash);
-- RLS apply (TenantScoped).
```

Migration `0036_invitations.py` (assuming we land DR.7 + this before any other migration). Standard create_table + RLS apply.

## Backend endpoints

| Endpoint | Auth | Behaviour |
|---|---|---|
| `POST /api/v1/invitations` | `users.write` | Body: `{email, role_id}`. Generates a random 32-byte token, bcrypt-hashes it, writes the invitation row, sends email with link `{FRONTEND_URL}/accounts/accept-invite?token={raw_token}`. Audit-logs `invitation.sent`. |
| `GET /api/v1/invitations` | `users.read` | List pending (un-accepted, un-expired) invitations for the org. |
| `DELETE /api/v1/invitations/{id}` | `users.write` | Revoke an unredeemed invitation. |
| `GET /api/v1/invitations/lookup?token=…` | **unauthenticated** | Validates the raw token; returns `{email, role_name, org_name}` if valid (so the accept page can show "Sarah, you're being invited to Core CRM Demo as an Owner"). 404 if invalid/expired/redeemed. |
| `POST /api/v1/invitations/accept` | **unauthenticated** | Body: `{token, password, first_name, last_name, phone}`. Validates token, hashes password, writes one row each into tbl_user_login + tbl_user_info + tbl_organization_members (same shape as `POST /users` from 2.5.1), marks invitation accepted, **logs the user in** (returns JWT). |

Email sending: hook into whatever Phase 1.7 / Phase 3 communications module set up. If none exists yet, print the link to logs in dev and leave a TODO-equivalent (loud log line) — the user said no TODOs, so add a real `EmailBackend` interface with a `LogEmailBackend` impl that logs the body. The interface lets a future SMTP/SES backend slot in.

## Frontend

Two pages:

**A) Admin's invite modal** (replaces the "disabled invite button" from 2.5.2):
- Modal opens from /user/settings/users → email + role dropdown → Submit → success toast with "Invitation sent" + the link (visible in dev mode for testing).
- Also adds a "Pending invitations" sub-table on /user/settings/users that lists invited but un-accepted emails with a Revoke button.

**B) Recipient's accept page** at `/accounts/accept-invite?token=…`:
- On load → call `GET /invitations/lookup?token=…` → show "Hi! You're being invited to **{org_name}** as **{role_name}**" / 404 page if invalid.
- Form: first_name, last_name, phone, password, confirm-password.
- Submit → `POST /invitations/accept` → on success, the JWT comes back; persist it; redirect to `/user/dashboard`.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0036_invitations.py` | created |
| `api/src/app/core/invitations/models.py` | created |
| `api/src/app/core/invitations/router.py` | created |
| `api/src/app/core/invitations/service.py` | created (token generation, hashing, email send, accept flow) |
| `api/src/app/core/invitations/schemas.py` | created |
| `api/src/app/shared/email/__init__.py` | created — `EmailBackend` protocol |
| `api/src/app/shared/email/log_backend.py` | created — dev backend that logs the email body |
| `api/src/app/main.py` | register invitations_router |
| `app/src/app/features/user/core/settings/users/invite-modal.component.ts` | created |
| `app/src/app/features/user/core/settings/users/invite-modal.component.html` | created |
| `app/src/app/features/user/core/settings/users/users-page.component.{ts,html}` | modified — wire button to modal + render pending invitations |
| `app/src/app/features/accounts/accept-invite/accept-invite.component.{ts,html}` | created |
| `app/src/app/features/accounts/accounts.routes.ts` | modified — register accept-invite route |

**~14 files + 1 migration.**

## Tests

- Invite as admin → 201, invitation row written, email logged.
- Accept with valid token → user created in all 3 tables, JWT issued.
- Accept with expired token → 410.
- Accept with already-redeemed token → 410.
- Revoke a pending invitation → `expires_at` set to now, lookup returns 404.

## Smoke

```
.\docker-helper.cmd upgrade
# In browser as admin@core-demo.local:
#   /user/settings/users → click [Invite]
#   email=newhire@core-demo.local, role=Employee
#   submit → toast shows the accept link
#   pending invitations sub-table shows the entry
# Copy the link, open in a private/incognito window:
#   /accounts/accept-invite?token=… → form pre-filled with email + role
#   set password=Hire@123, name=New Hire
#   submit → automatically logged in → /user/dashboard
# Back in admin window: pending invitations sub-table now shows the invite as accepted (or removed).
```

## Risks

1. **Token collision** — random 32 bytes urandom + bcrypt hash. Vanishingly unlikely; still UNIQUE index on token_hash.
2. **Email backend missing** — dev backend logs; production cutover needs SMTP/SES wired (a Phase 6 deployment task).
3. **Email already in tbl_user_info** — `POST /invitations/accept` must check before inserting; if email exists (user previously deactivated), return 409 with "this email already belongs to a user — reactivate them instead".

## Rollback

`.\docker-helper.cmd downgrade 1` drops the `invitations` table. Revert the new/modified source files. No data lost in tbl_user_login/info/members (this step only adds new users when invites are accepted).
