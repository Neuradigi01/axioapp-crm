# Lead Infrastructure

A focused track for pipeline-management infrastructure on the Leads kanban. Sits outside the numbered phase tree — vertical-neutral, ship-when-ready, picked up alongside whichever main phase is active.

## Why this exists

Pipeline editing is fundamental to any CRM. Today, the Leads kanban renders the funnel correctly, but admin self-service is incomplete:

| Gap | What's missing today |
|---|---|
| **Rename / recolor / reorder stages from the UI** | Backend PATCH endpoint exists ([`pipelines/router.py:60`](../../API/src/app/core/pipelines/router.py)); `PipelinesApiService.updateStage()` exists ([`pipelines-api.service.ts:70`](../../APP/src/app/features/user/core/pipelines/pipelines-api.service.ts)); **zero frontend component calls it**. Admins cannot rename "Qualified" → "Vetted" through the UI. |
| **Add a stage** | No backend endpoint. No UI. Admins cannot insert "Demo Scheduled" between Contacted and Qualified. |
| **Delete a stage** | No backend endpoint. No UI. Admins cannot remove a stage (or safely relocate cards out of it). |
| **Permission-gated UI for stage management** | `pipelines.manage` permission exists and is granted to Owner/Admin ([`seed_core_demo_org.py:102`](../../API/src/app/scripts/seed_core_demo_org.py)). No component reads it for conditional rendering. |

These four gaps are what blocks a non-furniture tenant from making the Leads board their own. Pipeline-shape is a vertical assumption baked into the `base` pack — every tenant will want to bend it. They should not need a developer to do it.

## What this does NOT do

- Does not touch the pack manifest format or installer. `packs/base/pack.yaml` and the install logic are stable.
- Does not add a Settings → Pipelines tab. All affordances live inline on the Leads kanban. Settings-level pipeline management is a future concern (multi-pipeline orgs, pipeline templates, import/export).
- Does not change the schema. `pipelines` and `pipeline_stages` tables already carry every column we need. **No Alembic migration in this track.**
- Does not allow creating new `is_won` or `is_lost` stages from the UI. Terminal stages are pack-level invariants — the POST endpoint hardcodes both flags to `false`.
- Does not allow deleting `is_won` or `is_lost` stages. Backend returns 409; UI hides the affordance.
- Does not edit stage `key` after creation. `Lead.pipeline_stage` is a text column referencing the key; renaming the key is a data-migration concern, not a UI feature.
- Does not implement undo. The audit trail is the recovery path.
- Does not touch the pipeline list / table view, only the kanban board.

## Acceptance criteria

A brand-new tenant — say a real-estate broker — logs into the core-crm and, **without leaving the Leads page**, can:

1. **Rename a stage** ("Qualified" → "Site Visit") with one click and a save.
2. **Recolor a stage**.
3. **Reorder a stage** one position left or right (terminal stages excluded).
4. **Add a new stage** anywhere between two existing stages.
5. **Delete a stage** with zero leads instantly; with leads, see a confirmation that asks which stage to move them to.
6. **Be unable to delete or reorder** the Won or Lost stages — affordances hidden, backend rejects.
7. **Sees no edit affordances at all** if their role is Sales Executive / Employee (no `pipelines.manage`). The kanban looks read-only.

All changes happen for that org only. Other tenants on the platform see nothing change.

## Steps

Step files to be authored next. Tentative breakdown:

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | Backend: stage CRUD endpoints (POST add, DELETE with relocation) | Pending | ~½ day |
| 2 | Frontend: stage editor popover (rename / recolor / reorder + delete link) | Pending | ~½ day |
| 3 | Frontend: add-stage popover | Pending | ~¼ day |
| 4 | Frontend: wire affordances into pipeline-board (pencils, + Add, delete-confirm modal, permission gating) | Pending | ~½ day |

**Total: ~2 working days.** Each step independently verifiable; pause and report after each per rule 9.

## Dependencies

- `pipelines` module (Phase 2) — Done. Tables, models, PATCH endpoint, service-level `update_stage()` already in place.
- Admin UI patterns (Phase 2.5) — Done. Establishes the permission-driven settings pattern referenced here.
- The `base` pack must be installed on the org being tested. Installed on `core-demo` as of this session.

## File budget (rough estimate)

| Area | Files | Notes |
|---|---|---|
| Backend (step 1) | 3 modified — [router.py](../../API/src/app/core/pipelines/router.py), [service.py](../../API/src/app/core/pipelines/service.py), [schemas.py](../../API/src/app/core/pipelines/schemas.py) | + 1 test file |
| Frontend new components (steps 2, 3) | 3 components × {`.component.ts`, `.component.html`} = 6 files | Lives under [`features/user/core/pipelines/`](../../APP/src/app/features/user/core/pipelines/) |
| Frontend modified (step 4) | 2 — [pipeline-board.component.ts](../../APP/src/app/features/user/core/pipelines/pipeline-board.component.ts), [.html](../../APP/src/app/features/user/core/pipelines/pipeline-board.component.html) | + permission reader if not exposed |
| Tests | ~1 backend pytest file covering POST/DELETE happy + invariant paths | |

**Total ~12 files, ~680 LOC.** Within the per-step rule of < 10 files / < 400 lines each (steps split accordingly).

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| Only `pipelines.manage` can mutate stages | Backend: `require_permissions("pipelines.manage")`; Frontend: `@if (canManage())` |
| `is_won` / `is_lost` stages cannot be deleted | Backend: DELETE returns 409 |
| `is_won` / `is_lost` stages cannot be reordered (in UI) | Frontend: hide `← →` buttons |
| `is_won` / `is_lost` flags are immutable post-install | Backend: PATCH schema forbids; POST hardcodes false |
| Stage `key` is immutable | Backend: not in any mutation schema |
| Cannot delete a stage with leads in it silently | Backend: 409 with `cards_in_stage` count → UI confirm modal with relocation dropdown |
| Per-org isolation | `org_id` on every row + RLS + tenant context — unchanged from existing model |

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`. All scope is `core/pipelines/`.
- ✅ Rule 2: No new tables; existing tables already carry `org_id` and RLS.
- ✅ Rule 3: Custom fields not touched.
- ✅ Rule 4: No new dynamic forms; pipeline editor is static UI for known fields.
- ✅ Rule 5: Sidebar registry unchanged. No new routes.
- ✅ Rule 6: Permission registry unchanged. Existing `pipelines.manage` is consumed.
- ✅ Rule 7: `pack.yaml` untouched. Per-org runtime customisation, not pack edits.
- ✅ Rule 8: Each step verifiable in < 30 min (one component or one backend slice each).
- ✅ Rule 9: Stop-and-report after every step.
- ✅ Rule 10: No TODOs. Terminal-stage rules enforced or feature withheld — no half-built switches.

## After this track

- Pipeline-shape becomes a tenant's own — they can mould the Leads funnel to their business without a developer.
- Foundation for a future Settings → Pipelines tab that adds multi-pipeline management, templates, and import/export.
