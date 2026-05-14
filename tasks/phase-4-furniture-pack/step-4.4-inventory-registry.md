# Step 4.4 — Inventory & Warehouse — backend (registry)

**Goal:** Register the inventory module in the module registry with permissions and menu metadata. Sidebar should automatically show "Inventory" via the registry endpoint.
**Phase:** 4
**Depends on:** 4.3, 1.8
**Status:** COMPLETED OK

## Scope
**In-scope:**
- `api/src/app/packs/furniture/modules/inventory/module.py` exporting `MODULE = ModuleDescriptor(id='inventory', layer='pack', name='Inventory & Warehouse', icon='warehouse', route='/api/v1/inventory', frontend_route='/inventory', menu_position=20, permissions=['inventory.read','inventory.write','inventory.dispatch','inventory.transfer'])`.
- Auto-discovery picks it up at startup (no core changes).
- Update furniture pack manifest's `module_permissions.inventory` so default roles get the right perms (e.g., Warehouse Manager all, Sales Executive read-only).

## Files to touch
- `api/src/app/packs/furniture/modules/inventory/module.py` (created)
- `api/src/app/packs/furniture/pack.yaml` (modified — `module_permissions.inventory`)

## Plan
1. Define MODULE descriptor.
2. Append `module_permissions` block; re-run installer for demo org.
3. Verify `GET /modules` shows Inventory.

## Tests to add
- `tests/test_inventory_module_registered.py` — auto-discover finds it.

## Verification checklist
**Backend:**
- `GET /modules` (admin) → Inventory listed.
- `GET /pipelines` etc. unaffected.
**Frontend:**
- visit `/` → sidebar shows "Inventory & Warehouse" entry (route 404 page until 4.5).

## Self-check (10 rules)
- [ ] Rule 5: sidebar from registry — module shows up without core changes.
- [ ] Rule 6: permissions registered.

## Stop & report
Await "proceed" before Step 4.5.
