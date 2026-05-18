# Step 1 — Backend: stage CRUD endpoints

**Goal:** Add the two missing pipeline-stage endpoints (POST to add, DELETE to remove with lead relocation) so the kanban editor on the Leads page has a full backend to call. PATCH already exists; this step makes it a real CRUD surface.
**Track:** Lead Infrastructure
**Status:** Pending

---

## Scope

Two new endpoints under `/api/v1/pipelines/{pipeline_key}/stages`, both gated on the existing `pipelines.manage` permission.

| Endpoint | Permission | Behaviour |
|---|---|---|
| `POST /pipelines/{pipeline_key}/stages` | `pipelines.manage` | Add a new stage. Body: `{name, color?, after_stage_key?}`. Auto-derives `key` by slugifying `name`; rejects with 422 if key collides within the pipeline. If `after_stage_key` provided, inserts immediately after that stage and shifts every subsequent stage's `display_order` up by 1 (uses the `INITIALLY DEFERRED` constraint trick that PATCH already relies on); if omitted, appends at the end. **`is_won` and `is_lost` always hardcoded to `false`** — creating terminal stages from the API is forbidden by design (pack-level concern). |
| `DELETE /pipelines/{pipeline_key}/stages/{stage_id}` | `pipelines.manage` | Remove a stage. Optional query param `move_leads_to=<key>` names the relocation target. Rules: (a) **409** if `stage.is_won` or `stage.is_lost` is `true`; (b) count rows in every registered pipeline-tracked table (today: `leads`) where `pipeline_stage = stage.key`; (c) if count > 0 and `move_leads_to` not provided, return **409** with `{cards_in_stage: N, must_provide: "move_leads_to"}`; (d) if count > 0 and `move_leads_to` provided, UPDATE all those rows to the target stage's key in the same transaction, then DELETE the stage; (e) `display_order` gaps on remaining stages are acceptable — ordering still works. |

Audit events written per existing pattern:
- `pipelines.stage_created` (POST)
- `pipelines.stage_deleted` (DELETE) with `before` snapshot, `cards_moved_count`, and `cards_moved_to` key

## Why no schema migration

`pipeline_stages` and `leads` already carry every column needed. POST is a single INSERT (after a display_order shift via UPDATE); DELETE is an UPDATE on leads + a DELETE on the stage row. Existing unique constraints (`(pipeline_id, key)`, deferred `(pipeline_id, display_order)`) cover correctness.

## Invariants enforced server-side

| Rule | Where |
|---|---|
| Cannot create `is_won` / `is_lost` stages | `service.create_stage`: hardcodes both `false` regardless of payload |
| Cannot delete `is_won` / `is_lost` stages | `service.delete_stage`: checks flags before any other work, raises 409 |
| Cannot orphan a lead | `service.delete_stage`: counts cards first; demands relocation target |
| Cannot duplicate a `key` within a pipeline | DB unique constraint + pre-check in service for a clean 422 |
| Caller scoped to own org | `set_context` + RLS + ORM tenant filter (unchanged from existing model) |

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/pipelines/router.py` | add `POST /pipelines/{key}/stages`, `DELETE /pipelines/{key}/stages/{stage_id}` |
| `api/src/app/core/pipelines/service.py` | add `create_stage(...)`, `delete_stage(...)`. Reuse the existing `_PIPELINE_TRACKED_TABLES` registry for the per-card-table count + UPDATE in DELETE. |
| `api/src/app/core/pipelines/schemas.py` | add `StageCreate` (`name`, `color?`, `after_stage_key?`); keep `extra="forbid"` so callers can't sneak `is_won`/`is_lost` in |
| `api/tests/test_pipeline_stage_crud.py` | new — pytest scenarios per below |

**4 files. No migrations. No new tables.**

## Slug helper

`create_stage` slugifies `name` to derive `key`:

```
"Demo Scheduled"   →  "demo_scheduled"
"Pre-qualified!"   →  "pre_qualified"
"  vipBuyer "      →  "vipbuyer"
```

Rules: lowercase, alphanum + underscore, collapse runs, trim leading/trailing underscores. Lives as a small private helper in `service.py` — does not need to be a public utility. Reject with 422 if the resulting key is empty or collides.

## Tests

`tests/test_pipeline_stage_crud.py`:

- **POST happy path:** create `Demo Scheduled` after `contacted` → 201; new stage at `display_order=2`; `qualified/proposal/won/lost` all shifted up by 1; `is_won=false`, `is_lost=false`.
- **POST appends when `after_stage_key` omitted:** new stage gets `display_order = max + 1`.
- **POST key collision:** body with `name="New"` (slug collides with existing `new` stage) → 422 with clear detail.
- **POST attempting `is_won=true`:** rejected by Pydantic at schema layer (extra=forbid) → 422.
- **POST as Employee role:** 403.
- **DELETE happy path, empty stage:** stage with zero leads → 204; row gone.
- **DELETE stage with leads, no relocation target:** → 409 with `{cards_in_stage, must_provide}`.
- **DELETE stage with leads + valid `move_leads_to`:** all referenced lead rows now point to target stage; stage gone; one transaction.
- **DELETE `won` stage:** → 409 regardless of `move_leads_to`.
- **DELETE `lost` stage:** → 409.
- **DELETE as Employee:** → 403.
- **Audit:** after POST, one new `pipelines.stage_created` audit row; after DELETE, one `pipelines.stage_deleted` row carrying `cards_moved_count`.

## Smoke

```
.\docker-helper.cmd upgrade  # no-op, no migrations
docker exec template_api-api-1 pytest tests/test_pipeline_stage_crud.py -v

# manual curl as admin@core-demo.local against the base pack's leads pipeline:
POST   /api/v1/pipelines/leads/stages  {"name":"Demo Scheduled","after_stage_key":"contacted"}  → 201
GET    /api/v1/pipelines/leads                                                                  → 7 stages
DELETE /api/v1/pipelines/leads/stages/<demo_scheduled_uuid>                                     → 204
DELETE /api/v1/pipelines/leads/stages/<won_uuid>                                                → 409
```

## Rollback

Revert the 4 files. No DB state change.
