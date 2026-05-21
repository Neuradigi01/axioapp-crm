# Step 3 — Sidebar entry for Dashboard

**Goal:** Register the Dashboard as a real core module so it shows up in the sidebar at the very top (above Contacts), reachable from any page. No special-case sidebar hardcoding — Dashboard registers itself like every other module, per Rule 5.
**Track:** Dashboard
**Status:** Pending
**Depends on:** Step 1 (backend endpoint) and Step 2 (frontend page).

---

## Scope

One new file: `api/src/app/core/dashboard/module.py` exporting a `MODULE: ModuleDescriptor`. The startup `discover_modules()` sweep in `main.py`'s lifespan walks `core/*/module.py` automatically, so no `main.py` edit is needed; the dashboard descriptor lands in the registry on the next API reload, and the frontend sidebar (driven off `/api/v1/modules`) starts rendering the entry.

## The descriptor

```python
# api/src/app/core/dashboard/module.py
from src.app.core.module_registry import ModuleDescriptor


MODULE = ModuleDescriptor(
    id="dashboard",
    name="Dashboard",
    icon="layout-dashboard",
    layer="core",
    route="/api/v1/dashboard",
    frontend_route="/user/dashboard",
    menu_position=100,
    permissions=[],
)
```

Why these values:

| Field | Value | Reason |
|---|---|---|
| `menu_position` | `100` | Contacts is at 200, Leads at 250. 100 puts Dashboard at the very top — standard CRM convention for the home/landing entry. |
| `permissions` | `[]` | Per the module-registry contract (`list_for_user()`), an empty permission list is **public** — shown to every authenticated user regardless of role. Every role should see Dashboard. No new permission key needs to be coined. |
| `icon` | `"layout-dashboard"` | Lucide icon name. Matches the visual convention used elsewhere in the sidebar (Lucide-Angular is already imported). |
| `route` | `/api/v1/dashboard` | The mount point of `dashboard_router` from Step 1. Used by the registry for documentation; the sidebar reads `frontend_route` for navigation. |
| `frontend_route` | `/user/dashboard` | The Angular route from Step 2. |

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/dashboard/module.py` | created |

**1 file. No migrations. No frontend changes. No new permission keys.**

The sidebar template ([`sidebar.component.html`](../../APP/src/app/features/user/core/layout/sidebar.component.html)) already renders any descriptor `ModuleApiService.list()` returns, sorted by `menu_position`. New entries appear automatically.

## Plan

1. Create the new file with the descriptor above.
2. API auto-reloads (uvicorn `--reload` is on). The startup lifespan re-runs `discover_modules()` and finds the new file.
3. Frontend already polls `/api/v1/modules` on shell init — a hard refresh of the browser is enough to see the new entry.

## Tests

No new tests. The module registry's invariants are already covered by the existing registry tests (descriptor validation, sort order, permission filtering). The smoke below proves the wiring.

## Smoke

```
# Backend — verify the descriptor lands in the registry:
docker exec template_api-api-1 python -c "
import asyncio
from src.app.core.module_registry import discover_modules, registry

registry.clear()
discover_modules()
for m in registry.list():
    print(f'{m.menu_position or \"-\":>4}  {m.id:<20} {m.frontend_route}')
"
# Expected: dashboard appears first with menu_position=100, frontend_route=/user/dashboard.

# Or hit the endpoint directly as any logged-in user:
curl -s -H "Authorization: Bearer $TOK" http://localhost:8000/api/v1/modules | jq '.[] | select(.id == "dashboard")'

# Browser:
# 1) Hard-refresh as any role (Owner / Admin / Employee / custom).
# 2) Sidebar's top item is now "Dashboard" with the layout-dashboard icon, above "Contacts".
# 3) Click it → /user/dashboard loads.
# 4) routerLinkActive highlights the entry while on /user/dashboard.
```

## Risks

- **menu_position collision** — if anything else is already at 100, alphabetical fallback decides order. Today no other core module uses 100; verify with the smoke command above.
- **Empty permissions on a permission-gated sidebar** — `list_for_user()` already treats empty `permissions` as public per its contract. No risk of Dashboard accidentally being hidden from a role.
- **Cached module list on long-running sessions** — the frontend fetches `/api/v1/modules` on shell init. A user with an open tab from before this step shipped won't see Dashboard until they reload. Acceptable; hard-refresh resolves it.

## Rollback

Delete the single new file. API reload, hard-refresh frontend — sidebar reverts. Dashboard page itself remains reachable at `/user/dashboard` (Step 2's route is independent) — only the sidebar shortcut goes away.
