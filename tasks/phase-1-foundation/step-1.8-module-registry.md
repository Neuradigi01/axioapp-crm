# Step 1.8 — Module registry (backend)

**Goal:** Build the module registration mechanism (rules 5 + 6 of the master prompt) — modules register metadata (id, name, icon, route, permissions, menu_position, layer). Auto-discovery on startup. Expose `GET /api/v1/modules` for the frontend sidebar.
**Phase:** 1
**Depends on:** 1.6
**Status:** Pending

## Scope
**In-scope:**
- `api/src/app/core/module_registry.py`:
  - `ModuleDescriptor` dataclass (id, name, icon, layer='core'|'pack', route, menu_position, parent, permissions: list[str], frontend_route).
  - `ModuleRegistry` singleton with `register(descriptor)` and `list()`.
  - Auto-discovery: import every package under `app/core/` and `app/packs/{pack_id}/` looking for an optional `module.py` exporting `MODULE: ModuleDescriptor`.
- `app/core/permissions/service.py` extended: `register_permissions(keys: list[str])` ensuring every key from `MODULE.permissions` exists in the `permissions` table on startup (idempotent upsert).
- `GET /api/v1/modules` endpoint returning the registry **filtered by current user's permissions** — only modules the user has at least one permission for.
- Settings stub module: register a "Settings" module so the sidebar has at least one entry to render.
- Tests for: registration, permission registration, filtered list.

**Out of scope:**
- Frontend rendering — 1.10.
- Furniture pack modules registering — Phase 4.

## Files to touch
- `api/src/app/core/module_registry.py` (created)
- `api/src/app/core/modules_router.py` (created — `GET /api/v1/modules`)
- `api/src/app/core/permissions/service.py` (modified — `register_permissions`)
- `api/src/app/core/settings/__init__.py` (created)
- `api/src/app/core/settings/module.py` (created — exports `MODULE`)
- `api/src/app/main.py` (modified — startup hook to discover modules + register their permissions)

## Plan
1. Define `ModuleDescriptor`. Validation: id matches `[a-z][a-z0-9_]*`, route starts with `/`, permissions all match `module.action` shape.
2. Implement `ModuleRegistry`: dict by id, `register` raises on duplicate id, `list_for_user(perms)` filters.
3. Implement discovery: walk `src.app.core.*` and `src.app.packs.*` packages with `pkgutil`, attempt to import `<pkg>.module`, collect `MODULE` if present.
4. On startup, call `discover_modules()`, then for each module call `permissions.register_permissions(MODULE.permissions)` — bulk upsert.
5. Build the Settings stub: `MODULE = ModuleDescriptor(id='settings', name='Settings', icon='cog', layer='core', route='/api/v1/settings', frontend_route='/settings', menu_position=999, permissions=['settings.read','settings.write'])`.
6. Implement `GET /api/v1/modules`: returns `[ModuleDescriptorOut, ...]` filtered by current user permissions.
7. Add a small admin endpoint `POST /api/v1/dev/refresh-modules` (dev-only, gated by `APP_ENV=dev`) for hot-reloading the registry without restart.

## DB changes / migrations
- None (permissions table already exists from 1.5; we just upsert rows on startup).

## Tests to add
- `tests/test_module_registry.py` — register a fake module, list returns it; duplicate id raises.
- `tests/test_modules_endpoint.py` — admin user sees Settings module; user without `settings.read` does not see it.

## Verification checklist
**Backend:**
- run: `uv run uvicorn src.app.main:app` → log shows `discovered modules: ['settings']` (later: more).
- hit: `GET /api/v1/modules` with admin token → array containing Settings.
- run: `psql -c "SELECT key FROM permissions WHERE key LIKE 'settings.%';"` → settings.read, settings.write rows.
- run: `uv run pytest tests/test_module_registry.py -v` → green.

**Code review:**
- open `api/src/app/core/module_registry.py` — note the discovery walks both `src.app.core.*` and `src.app.packs.*` (rule 5).
- open `api/src/app/core/settings/module.py` — note the standalone module export pattern.

## Self-check (10 rules)
- [ ] Rule 5 (sidebar registry) implemented.
- [ ] Rule 6 (permissions registry) implemented.
- [ ] Core does not import from packs (the discovery loop walks pack packages but does not import pack modules into core; pack modules register THEMSELVES on import).
- [ ] No TODOs.

## Stop & report
Use the master-prompt stop template; await "proceed" before Step 1.9.
