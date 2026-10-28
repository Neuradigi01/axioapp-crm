# Step 2.5.2 — Users management page

**Goal:** Build `/user/settings/users` — a single page where an admin sees the team, edits roles, deactivates people, and clicks "Invite" to start the invite flow.
**Phase:** 2.5 — Core CRM Admin UI
**Status:** Pending
**Depends on:** 2.5.1 (backend endpoints)

---

## Scope

One Angular page + one service + one form. **No new sidebar entry** — slot under the existing `/user/settings` parent (DR.5 sidebar branding already shows Settings for the admin role; we add a "Users" tab in the settings layout).

## Routing + layout

```
/user/settings              (existing — landing)
  /users                    (NEW — this step)
  /roles                    (next step 2.5.3)
  /org                      (next step 2.5.4)
```

Settings layout has a left sub-nav: Users, Roles, Organization. Profile (2.5.5) is separate at `/user/profile`.

## UI

A table:

| Name | Email | Role | Status | Actions |
|---|---|---|---|---|
| Core Demo Admin | admin@core-demo.local | Admin | Active | [Edit] [Deactivate] |
| Core Demo Owner | owner@core-demo.local | Owner | Active | [Edit] [Deactivate] |
| … | … | … | … | … |

Top right: **[+ Invite user]** button → opens modal: email + role dropdown. Submits to `POST /api/v1/invitations` (2.5.6 endpoint; for 2.5.2 we just stub the button to disabled with a "Invite flow ships in 2.5.6" tooltip).

[Edit] opens an inline form: full_name, phone, role dropdown. Email is read-only.
[Deactivate] / [Activate] toggles status via `PATCH /users/{id}/status`.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/settings/users/users-page.component.ts` | created |
| `app/src/app/features/user/core/settings/users/users-page.component.html` | created |
| `app/src/app/features/user/core/settings/users/users-page.component.scss` | created |
| `app/src/app/features/user/core/settings/users/users.service.ts` | created — wraps `/api/v1/users` + `/roles` |
| `app/src/app/features/user/core/settings/settings.routes.ts` | modified — register `users` route |
| `app/src/app/features/user/core/settings/settings-layout/` | minor — add Users tab to sub-nav |

**6 files, all under `core/settings/users/`.** Angular standalone components + signals + typed reactive form (per CLAUDE.md stack rules). Tailwind only (no PrimeNG).

## Permission gating

Page resolver checks `users.read` in `RequestContext.permission_keys`. If missing → redirect to `/user/dashboard`. Edit/Invite/Deactivate buttons only render if `users.write` is in the set.

## Smoke

```
ng build --configuration development  # clean
# In browser, log in as admin@core-demo.local:
#   - Navigate /user/settings/users → table shows 3 users
#   - Edit Owner → change role to Employee → save → row updates
#   - Deactivate Employee → row greyed out, status=Inactive
#   - Re-login as Employee → "your account is inactive" 401
# Log in as employee@core-demo.local:
#   - Navigate /user/settings/users → redirect (no users.read on Employee role by default)
```

## Rollback

Delete the 4 new files + revert the 2 modified ones. No DB state change.
