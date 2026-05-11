# Step 2.9 — Pipelines engine: backend

**Goal:** `pipelines` and `pipeline_stages` tables. Endpoints to read pipelines and to move a card between stages with audit logging. Pipeline creation is via pack installer (Phase 4); admin can edit stage labels/colors/order but not keys.
**Phase:** 2
**Depends on:** 1.7 (audit), 1.4 (RLS)
**Status:** Pending

## Scope
**In-scope:**
- Models:
  - `Pipeline` (TenantScoped): id, org_id, key (unique per org, e.g. `leads`, `custom_orders`), name, created_at.
  - `PipelineStage` (TenantScoped): id, org_id, pipeline_id, key, name, color, display_order, is_won, is_lost.
- Migration + RLS + uniqueness on `(org_id, pipeline_id, key)`.
- Schemas: `PipelineOut` (with stages embedded), `StageUpdate` (label/color/order only).
- Service:
  - `list_pipelines()`, `get_by_key(key)`.
  - `move_card(pipeline_key, card_table, card_id, to_stage_key, user_id)` — generic helper used by Leads (2.11), Custom Orders (4.8). Updates the target row's `pipeline_stage` column + writes activity + audit log.
- Endpoints: `GET /pipelines`, `GET /pipelines/{key}`, `PATCH /pipelines/{key}/stages/{id}` (label/color/order).
- Permission: `pipelines.read`, `pipelines.manage` (edit labels/order).

**Out of scope:**
- Frontend kanban — 2.10.
- Lead-specific endpoints — 2.11.

## Files to touch
- `api/app/core/pipelines/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0010_pipelines.py` (created)
- `api/app/main.py` (modified)

## Plan
1. Models + migration. `pipeline_stages` has uniqueness on `(pipeline_id, key)` AND `(pipeline_id, display_order)`.
2. `move_card` accepts a target table name + id; uses raw SQL `UPDATE` with parameter binding (validates table is in an allowlist of pipeline-tracked tables).
3. Audit log per move with `before`/`after` stage.
4. Activity log per move with `type='status_change'`.
5. Read endpoints return stages ordered by `display_order`.

## DB changes / migrations
- `0010_pipelines`: 2 tables, RLS, indexes.

## Tests to add
- `tests/test_pipelines.py` — CRUD reads, stage update, RLS.
- `tests/test_pipeline_move.py` — moving a fake card emits audit + activity.

## Verification checklist
**Backend:**
- `GET /pipelines` → empty initially (pipelines created in 4.2 by pack installer).
- after seed: `GET /pipelines/leads` → stages array.

## Self-check (10 rules)
- [ ] Engine is generic (no furniture knowledge).
- [ ] org_id + RLS.

## Stop & report
Await "proceed" before Step 2.10.
