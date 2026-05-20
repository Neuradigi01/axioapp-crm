# Step 2 — Role-template registry + auto-seed on org creation

**Goal:** Define `Owner`, `Admin`, `Employee` as vertical-neutral *role templates* in code (not as fixed system rows), and expose an installer that stamps them into a new org's `roles` + `role_permissions` tables. On normal signup (Step 1) all three auto-instantiate; an Owner can later pull in additional templates ("Sales Manager", "Support Agent") via "+ Add from template" on the Roles page.
**Track:** RBAC, Ownership & Self-Signup
**Status:** Pending
**Depends on:** 1.5 (roles + permissions schema), 2.5.3 (Roles page UI we'll extend).

---

## Scope

A registry of role templates, plus an installer that resolves a template's permission-key list against the live `permissions` registry and writes the resulting `roles` + `role_permissions` rows for a given `org_id`. UI surface: a button on `/user/settings/roles` that shows the templates not yet instantiated in this org and instantiates them on click.

## Template registry shape

```python
# api/src/app/core/permissions/role_templates.py

@dataclass(frozen=True)
class RoleTemplate:
    key: str                 # "owner" | "admin" | "employee" | "sales_manager" | ...
    name: str                # "Owner" — also the seeded `roles.name`
    is_system: bool          # True for Owner (locked); False for Admin/Employee/custom
    is_owner: bool           # True only for Owner; one-per-org invariant enforced downstream
    permission_keys: list[str]   # resolved against the live permissions registry
    description: str
    auto_install_on_org_create: bool  # True for owner/admin/employee; False for others

ROLE_TEMPLATES: dict[str, RoleTemplate] = {
    "owner":    RoleTemplate(key="owner",    name="Owner",    is_system=True,  is_owner=True,
                              permission_keys=ALL_KEYS,        # "*" — resolved to every registered key
                              description="Full system access. Cannot be edited or deleted.",
                              auto_install_on_org_create=True),
    "admin":    RoleTemplate(key="admin",    name="Admin",    is_system=False, is_owner=False,
                              permission_keys=[..., "users.write", "roles.write", ...],  # no billing.*, no ownership.*
                              description="Manage users, leads, contacts, deals; view reports; configure settings.",
                              auto_install_on_org_create=True),
    "employee": RoleTemplate(key="employee", name="Employee", is_system=False, is_owner=False,
                              permission_keys=["leads.read_assigned", "tasks.write_own", "contacts.write_own", "reports.read_limited"],
                              description="View assigned leads; manage own tasks/contacts/deals; limited reports.",
                              auto_install_on_org_create=True),
}
```

The concrete `permission_keys` lists for Admin and Employee are filled in from the keys already registered by core modules at Step 1.5 / 1.6 / 1.7 time and each subsequent module's registration. The dataclass is the source of truth; no hardcoded furniture keys here (Rule 7 — those come from the furniture `pack.yaml`).

`ALL_KEYS` for Owner is a sentinel — the installer resolves it at install time by reading every key from the live `permissions` table. This means Owner's grant set automatically picks up new permissions as modules register them.

## Installer

```python
# api/src/app/core/permissions/role_templates.py

async def install(db: AsyncSession, org_id: UUID, template_keys: Iterable[str] | None = None) -> list[Role]:
    """Stamp the given templates into the org. If template_keys is None, install all
    templates with auto_install_on_org_create=True."""
```

Behaviour:

- Idempotent — if a role with the same `(org_id, name)` already exists, skip (no error).
- Reads the live `permissions` table to resolve keys. If a template references a key that hasn't been registered yet, **fail loudly** (`UnknownPermissionKey`) — better to break the install than silently miss a permission.
- All inserts in a single transaction. Caller is expected to manage outer transaction boundary (Step 1's signup transaction owns it).
- For `is_owner=True` templates, asserts no existing Owner role for the org — raises `OwnerAlreadyExists` if violated.

## Backend endpoints (Roles page extension)

| Endpoint | Auth | Behaviour |
|---|---|---|
| `GET /api/v1/role-templates` | `roles.read` | Returns the registry as JSON, with a per-template `installed: bool` flag indicating whether the caller's org has already instantiated it. |
| `POST /api/v1/role-templates/{key}/install` | `roles.write` | Calls `role_templates.install(org_id, [key])`. Returns 201 with the new `Role` row; 409 if already installed; 422 if the key is unknown. Owner templates rejected via this endpoint — Owner is only ever installed by Step 1's signup flow (one-per-org invariant). |

## Frontend changes (extend Step 2.5.3)

The Roles page from 2.5.3 currently renders rows for whatever's in `GET /roles`. Add:

1. **Top-right button:** **+ Add from template** — opens a side-drawer / modal listing the un-installed templates (filtered from `GET /role-templates` where `installed=false`).
2. Each row in that list has [Add to my org] which calls `POST /role-templates/{key}/install` and refreshes the parent table.
3. **Owner row label:** show a `🔒` icon + tooltip "System role — cannot be edited or deleted" next to its name. Edit/Delete buttons hidden. (2.5.3 already disables edits on `is_system` rows — this step extends the visual treatment.)
4. **Admin / Employee rows:** **editable / deletable** (they are `is_system=false` per the registry). Customer can rename "Admin" → "Manager" or delete entirely; that org just has no Admin role afterwards.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/permissions/role_templates.py` | created — registry + installer |
| `api/src/app/core/permissions/router.py` | modified — add `GET /role-templates`, `POST /role-templates/{key}/install` |
| `api/src/app/core/permissions/schemas.py` | modified — `RoleTemplateOut`, `RoleTemplateListResponse` |
| `api/src/app/scripts/seed_admin_user.py` | modified — replace its hand-rolled "admin role + permissions" inserts with a call to `role_templates.install(org_id, ["admin"])`. Keeps the seed user, eliminates the duplication. |
| `api/tests/test_role_templates.py` | created |
| `app/src/app/features/user/core/settings/roles/roles-page.component.{ts,html}` | modified — add the **+ Add from template** button + drawer |
| `app/src/app/features/user/core/settings/roles/roles.service.ts` | modified — `listTemplates()`, `installTemplate(key)` |
| `app/src/app/features/user/core/settings/roles/template-picker.component.{ts,html}` | created — the side-drawer |

**~9 files. No migrations.** Templates are code-defined; the only DB writes are into the existing `roles` + `role_permissions` tables.

## Tests

`api/tests/test_role_templates.py`:

- **Registry listing:** `GET /role-templates` as a fresh-org Owner → all four (owner, admin, employee, and any others) listed; owner/admin/employee have `installed=true`, others `installed=false`.
- **Install custom template:** assume a `sales_manager` template is registered → `POST /role-templates/sales_manager/install` → 201, new `roles` row + `role_permissions` for the listed keys.
- **Idempotent install:** call install twice → second call returns 409 (already installed) with no extra rows written.
- **Reject Owner install:** `POST /role-templates/owner/install` → 403 / 422. Owner only flows via signup.
- **Unknown key in template:** monkey-patch a bogus key into a template → install raises `UnknownPermissionKey`; transaction rolls back; no partial `roles` row.
- **Single-org-Owner invariant:** simulate two attempts to insert an Owner role into the same org → second raises `OwnerAlreadyExists`. (Per-DB-row enforcement comes from the partial unique index in track invariants.)

## Smoke

```
.\docker-helper.cmd upgrade
docker exec template_api-api-1 pytest tests/test_role_templates.py -v

# Browser (after Step 1 lands):
#   sign up as a new owner → /user/settings/roles
#   table shows Owner (locked), Admin, Employee
#   click [+ Add from template] → drawer shows un-installed templates (initially empty if registry only has the 3)
# Backend-only smoke for a 4th template:
#   register a `sales_manager` template in role_templates.py
#   restart api → /user/settings/roles → drawer now shows Sales Manager
#   click [Add to my org] → table now has 4 rows
```

## Risks

- **Permission-key drift:** if a template lists a key that a future code change removes, install starts failing. Mitigation: tests pin the registry shape. Long-term, we could lint against the union of registered keys in CI.
- **`ALL_KEYS` sentinel for Owner:** new modules need to call `permissions.register()` *before* signup runs to be included in Owner's grants. This is already how the registry works at app startup; no new ordering issue.
- **Editing Admin's permissions creates per-org drift:** an Owner edits Admin to remove `users.write`. Then a colleague signs up later — *their* org gets the un-edited template defaults. This is correct behaviour (templates are templates, instantiated roles are per-org); call it out in the role page tooltip.

## Rollback

Revert the 9 source files. No DB state to roll back (no migrations). Newly-installed roles in orgs that already used the feature remain in place — same as any per-org role row.
