# Step DR.5 — Per-org sidebar branding

**Goal:** Replace the hardcoded "FurnitureCRM" text in the sidebar header with the current org's name + a small pack indicator, so logging into the `core-demo` org doesn't show "FurnitureCRM" branding.
**Phase:** 4.5 — Demo Roles Setup (side task)
**Depends on:** DR.1, DR.2, DR.3
**Status:** Parked (not started)

## Why this exists

Today the sidebar header at `app/src/app/features/user/core/layout/sidebar.component.html` literally says:

```html
<span class="text-base font-semibold tracking-tight">FurnitureCRM</span>
```

When you log in as `admin@core-demo.local` (the core-only org), the sidebar still says "FurnitureCRM". That's a branding leak — the product name is showing in an org that has no furniture pack installed.

The proper behaviour is the sidebar should brand itself to the current org:
- `core-demo` org → "Core CRM Demo · core"
- `demo` org → "Demo Furniture Store · furniture"
- Any future tenant → their `organizations.name` + their `pack_id`.

## Scope

**In-scope:**
- Expose the current org's identity on `/users/me`. Today the endpoint returns the User row only. Extend the `UserMe` schema to include a nested `org: {id, name, slug, pack_id}` block. Backend reads from the already-loaded `User.org` relationship.
- Frontend: in `auth.service.ts` (the furniture one used by `/user/...`), store the org info from the `/me` response into a signal alongside the user info.
- Update `sidebar.component.ts/.html`:
  - Inject the auth service.
  - Replace the hardcoded "FurnitureCRM" text with `{{ org()?.name ?? 'CRM' }}`.
  - Below the name, add a tiny pack chip: `<span class="rounded-full ... text-zinc-500">{{ org()?.pack_id }} pack</span>`.
- Collapsed-sidebar mode: show first letter of org name instead of hardcoded "F".

**Out of scope:**
- Logo upload / theming (just text for now).
- Header bar branding (only sidebar — the header doesn't show "FurnitureCRM" currently).
- Refactoring the existing legacy admin app's branding (`/admin/...` stays as-is per CLAUDE.md).

## Files to touch

- `api/src/app/core/users/schemas.py` (modified — extend `UserMe` with nested `org` block)
- `api/src/app/core/users/router.py` (modified — populate `org` in the `/me` response)
- `app/src/app/features/user/core/auth/auth.service.ts` (modified — store org from /me response)
- `app/src/app/features/user/core/layout/sidebar.component.ts` (modified — inject auth + expose org signal)
- `app/src/app/features/user/core/layout/sidebar.component.html` (modified — replace hardcoded text)

## Plan

1. **Backend.**
   - Add a small Pydantic `OrgSummary { id, name, slug, pack_id }` schema.
   - Add `org: OrgSummary` field to `UserMe`.
   - In the `/users/me` router, eagerly load `User.org` (joinedload) and populate.
2. **Frontend — auth service.**
   - When `/me` returns, persist `{name, slug, pack_id}` into a `currentOrg` signal on `FurnitureAuthService`. Clear it on logout.
3. **Frontend — sidebar component.**
   - Inject `FurnitureAuthService`. Expose `org = this.auth.currentOrg`.
   - In template: replace the literal "FurnitureCRM" / "F" with the org name / first letter.
   - Add a tiny capitalize-cased pack indicator below the name (only when sidebar is expanded).

## DB changes / migrations

None.

## Tests to add

- `tests/test_users_me_includes_org.py` — `/me` response now includes `org.name`, `org.slug`, `org.pack_id`.
- The TypeScript bits are covered by the existing `ng build` type-check.

## Verification checklist

**Frontend (after the change):**
- Log in as `admin@core-demo.local` → sidebar reads **"Core CRM Demo"** with a "core pack" chip below.
- Log out → log in as `admin@demo.local` → sidebar reads **"Demo Furniture Store"** with a "furniture pack" chip.
- Collapsed sidebar: shows "C" for core-demo, "D" for demo.
- Refreshing the page mid-session re-fetches `/me` and shows the correct org name (no flash of "FurnitureCRM").

**Backend:**
- `GET /api/v1/users/me` (with any of the 4 test tokens) returns `{..., org: {id, name, slug, pack_id}}` with the matching org info.

## Self-check (10 rules)

- [ ] Rule 1 — sidebar component lives in `core/layout/`, doesn't import from `packs/`.
- [ ] Rule 8 — ~5 files, < 80 lines of new code.
- [ ] Rule 10 — no hardcoded "FurnitureCRM" string remains in `core/layout/`.
- [ ] Legacy `/admin/...` branding is verifiably untouched (rule from CLAUDE.md).

## Stop & report

Take a screenshot of both sidebars (Core CRM Demo vs Demo Furniture Store) — that's the proof. Then resume Phase 5.
