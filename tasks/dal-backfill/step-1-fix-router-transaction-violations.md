# Step 1 — Fix router transaction violations (inventory, leads, dev)

**Goal:** Remove `db.commit / db.rollback / db.refresh / db.flush / db.execute / select()` from three router files. Move transaction logic into `service.py`; create `data_access.py` for `dev` (which currently has neither a service nor a DAL).
**Status:** Pending
**Depends on:** Audit findings 2026-06-25.

---

## Scope

In-scope: three routers and their downstream service files. Behaviour must not change — endpoints, payloads, status codes, side effects identical before and after.

Out of scope:
- Backfilling DALs for these modules (covered in Step 8 for `leads`, Step 13 for `packs/inventory`).
- Wider DAL relocation for any other module.

## Files to touch

| File | Action | What |
|---|---|---|
| `API/src/app/packs/furniture/modules/inventory/router.py` | modify | Remove `db.flush / commit / rollback / refresh`; remove ORM `CatalogItem(...)` instantiation; call a new `service.create_inventory_item(...)` |
| `API/src/app/packs/furniture/modules/inventory/service.py` | modify | Absorb the transaction orchestration that was in the router (lines ~204–254); add `upload_cover_service(...)` |
| `API/src/app/core/leads/router.py` | modify | Remove `await db.commit()` + `await db.refresh()` in `put_routing_config_endpoint`; remove direct import of `tenants.data_access`; route through `tenants` service |
| `API/src/app/core/leads/service.py` | modify | New `update_routing_config_service(...)` that absorbs the commit/refresh |
| `API/src/app/core/tenants/service.py` | modify | Add a thin `get_or_create_settings_service(...)` wrapper if not already exposed (callable by leads service instead of reaching into tenants DAL directly) |
| `API/src/app/core/dev/router.py` | modify | Remove `select(...)` + `await db.execute(stmt)`; call `service.list_dev_X_service(...)` |
| `API/src/app/core/dev/service.py` | **NEW** | Wraps the query; no business logic since dev is internal tooling |
| `API/src/app/core/dev/data_access.py` | **NEW** | One function: holds the `select() / db.execute()` |

**~8 files. ~250 lines net delta.**

## Plan

1. **Inventory** — read `router.py` lines 204–254 + 288–289. Move the whole `create_item_endpoint` body into `service.create_inventory_item(db, payload, org_id, user_id)`. Service does: build `CatalogItem(...)`, `db.add`, `db.flush`, `db.commit`, `db.refresh(inv)`, return inv. Same for `upload_cover_endpoint`. Router becomes a thin call: `return service.create_inventory_item(db, payload, user.org_id, user.id)`.
2. **Leads** — `put_routing_config_endpoint`: remove direct `from src.app.core.tenants import data_access`. Add `update_routing_config_service(db, org_id, payload)` in `leads/service.py`. Service calls a tenants service method (add `get_or_create_settings_service` in tenants/service.py if not present) and does its own commit/refresh.
3. **Dev** — create `dev/service.py` + `dev/data_access.py`. Move the existing `select(...).select_from(...).join(...)` into a single DAL function `list_dev_<thing>(db)`. Service wraps it. Router calls service. No commit needed — it's a read.
4. Run module-level smokes (one endpoint each) against Ajay's Workspace via the local UI.
5. Grep proof: `rg "(db\.commit|db\.rollback|db\.flush|db\.refresh|db\.execute|^from .*select)" inventory/router.py leads/router.py dev/router.py` → no matches in the three files.

## DB changes / migrations

None.

## Tests

- If module pytest exists for inventory/leads/dev, run after change. No new tests in this step — behaviour-preserving relocation only.

## Smoke

- **Inventory:** create a product via `/user/inventory` → row appears, no 500.
- **Leads:** Settings → Lead Routing → save config → reload → config persisted.
- **Dev:** open whatever dev page consumes `dev/router.py` → data lists as before.

## Risks

- Inventory's transaction had explicit `await db.rollback()` on error path. Service must keep the same try/except pattern so error semantics don't change.
- Leads' `get_or_create_settings` may already be in tenants/service. If so, just import it; don't duplicate.

## Self-check (10 rules)

`core/` doesn't import `packs/`. ✓ `org_id` filters preserved on every call. ✓ Custom-fields untouched. ✓ Forms untouched. ✓ Sidebar/registry untouched. ✓ Permissions unchanged. ✓ Pack manifest untouched. ✓ < 10 files / < 400 lines. ✓ Stop-and-report. ✓ No TODOs / no commented-out code. ✓
