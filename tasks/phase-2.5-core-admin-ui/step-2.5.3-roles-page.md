# Step 2.5.3 — Roles + permission grants page

**Goal:** Build `/user/settings/roles` — list existing roles, create custom ones, and edit which permission keys each grants.
**Phase:** 2.5 — Core CRM Admin UI
**Status:** Pending
**Depends on:** 2.5.1 (backend endpoints)

---

## Scope

One Angular page + service. The hardest part is the **permission grants matrix** — a grouped-by-module checkbox panel that scales as packs add permission keys.

## UI

**Top section — Role list:**

| Role | System? | Members | Permissions | Actions |
|---|---|---|---|---|
| Admin | ✓ | 1 | 44 | [View] (read-only — system role) |
| Owner | ✓ | 1 | 41 | [View] |
| Employee | ✓ | 1 | 21 | [View] |
| (no custom roles yet) | | | | |

Top right: **[+ Create role]** opens an editor.

**Editor view (full-page or side-drawer):**

- Role name (text input)
- Permission grants — grouped by `permissions.module`:
  ```
  ▸ Contacts        ☑ contacts.read   ☑ contacts.write
  ▸ Leads           ☑ leads.read      ☑ leads.write
  ▸ Walk-ins        ☐ walkins.read    ☐ walkins.write
  ▸ Tasks           ...
  ```
- Save / Cancel buttons.

For **system roles** the editor is read-only (CLAUDE.md: pack-installed and core-seeded roles shouldn't drift; admins create their own custom roles instead).

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/settings/roles/roles-page.component.ts` | created |
| `app/src/app/features/user/core/settings/roles/roles-page.component.html` | created |
| `app/src/app/features/user/core/settings/roles/role-editor.component.ts` | created |
| `app/src/app/features/user/core/settings/roles/role-editor.component.html` | created |
| `app/src/app/features/user/core/settings/roles/roles.service.ts` | created — wraps `/api/v1/roles` + `/permissions` |
| `app/src/app/features/user/core/settings/settings.routes.ts` | modified — register `roles` route |
| `app/src/app/features/user/core/settings/settings-layout/` | minor — add Roles tab |

**7 files.** Permission grants matrix rendered with @for over the module-grouped permissions list returned by `GET /permissions`.

## Smoke

```
ng build --configuration development  # clean
# In browser as admin@core-demo.local:
#   - /user/settings/roles → table shows Admin/Owner/Employee with permission counts 44/41/21
#   - Click [+ Create role] → editor opens
#   - Name = "Showroom Lead", tick 8 permission keys (contacts.read/write, leads.read/write, walk_ins.read/write, calls.read/write)
#   - Save → row appears in table with permissions=8
#   - Re-edit, remove 2 keys → save → count drops to 6
#   - Try to edit Admin (system) → buttons disabled
#   - Delete custom role → row removed
#   - Assign the role to a user via /settings/users → role updated; /users/me on that user reflects new perms
```

## Risks

- **Permission key churn:** the registry is populated at app startup. A custom role created in dev could reference a key that doesn't exist after a code change. Mitigation: server-side validation in `POST /roles` rejects unknown keys.
- **Loop edit on system role:** UI disables it; backend also enforces `is_system=false` per 2.5.1.

## Rollback

Delete the 5 new files + revert 2 modified ones. No DB state change.
