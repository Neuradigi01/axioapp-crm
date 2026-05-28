# Step DR.6.7b — Drop remaining `users.id` FK constraints on furniture-pack tables

**Goal:** Apply the same FK cutover that DR.6.7 did for core CRM, but for the furniture pack's 3 remaining `users.id` FK constraints. Same reasoning, same pattern, separate migration so pack-side cleanup never touches core schema (and vice versa).

**Phase:** 4.5 — Demo Roles Setup (DR.6 soak cleanup)
**Depends on:** DR.6 (Done), DR.7 (Done), DR.6.7 (Done — core CRM cutover)
**Status:** Pending

---

## Why a separate migration from DR.6.7

Per the user instruction "keep it separate from my core CRM," pack-side schema changes ride in their own Alembic revision. Two upsides:

- Rolling back the pack cutover (`alembic downgrade -1`) leaves the core CRM cutover intact.
- An org that uninstalls the furniture pack later still has a clean per-table migration history for pack tables.

## Scope

**In scope — furniture pack (3 FKs, 2 model files):**

| Table | Column | ondelete | Constraint name |
|---|---|---|---|
| fp_inventory_movements | user_id | SET NULL | fp_inventory_movements_user_id_fkey |
| fp_custom_orders | assigned_to_id | SET NULL | fp_custom_orders_assigned_to_id_fkey |
| fp_custom_order_stages | user_id | SET NULL | fp_custom_order_stages_user_id_fkey |

**Out of scope:**

- Anything in core CRM (already handled by DR.6.7).
- Dropping the legacy `users` table (DR.6.8, later).
- Retargeting FKs to `tbl_user_login.legacy_uuid` (same rejection rationale as DR.6.7).

## Files to touch

| File | Change |
|---|---|
| `tasks/phase-4.5-demo-roles-setup/step-dr.6.7b-drop-pack-users-fks.md` | created (this file) |
| `API/alembic/versions/0063_drop_pack_users_id_fks.py` | created — 3 `drop_constraint` in `upgrade()`, 3 `create_foreign_key` in `downgrade()` |
| `API/src/app/packs/furniture/modules/inventory/models.py` | remove `ForeignKey("users.id", ondelete="SET NULL")` from `InventoryMovement.user_id` |
| `API/src/app/packs/furniture/modules/custom_orders/models.py` | remove `ForeignKey("users.id", ondelete="SET NULL")` from `CustomOrder.assigned_to_id` and `CustomOrderStageChange.user_id` |

Both model files have other (non-users) `ForeignKey` declarations, so the `ForeignKey` import stays.

No router, service, schema, or test changes.

## Rollback

`alembic downgrade -1` recreates all 3 constraints with their original `ondelete=SET NULL`. Safe as long as the legacy `users` table still exists.

## Smoke checklist

In the API container:

- [ ] `UPDATE fp_inventory_movements SET user_id = '<MS Dhoni UUID>' WHERE id = <any>` succeeds (no FK violation).
- [ ] `UPDATE fp_custom_orders SET assigned_to_id = '<MS Dhoni UUID>' WHERE id = <any>` succeeds.
- [ ] `UPDATE fp_custom_order_stages SET user_id = '<MS Dhoni UUID>' WHERE id = <any>` succeeds.

Each test reverts itself afterwards so the data state is unchanged. Tests skip cleanly if the table has no rows (pack tables in Ajay's Workspace are likely empty since the furniture pack isn't installed there).

## Stop & report

After all 3 smoke checks pass (or skip cleanly), report: "DR.6.7b done. 3 pack FKs dropped, smoke green/skipped. Pack-side users.id FKs are now in line with core."
