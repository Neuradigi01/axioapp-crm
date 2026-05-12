# Step 2.10 — Pipelines engine: frontend

**Goal:** Reusable `<app-pipeline-board>` (kanban) and `<app-pipeline-list>` (table) components. Stage config from API. Drag-and-drop calls the move endpoint. Reused by Leads and Custom Orders.
**Phase:** 2
**Depends on:** 2.9
**Status:** COMPLETED

## Scope
**In-scope:**
- `app/src/app/features/user/core/pipelines/`:
  - `pipelines-api.service.ts`
  - `pipeline-board.component.ts/.html` — inputs `(pipelineKey, items, itemTemplate)`. Stages as columns; items grouped by stage; cdk-drag-drop between columns; `(itemMoved)` output.
  - `pipeline-list.component.ts/.html` — same inputs, table view with stage column; row-edit menu for stage change.
- Tailwind only.
- Stage colors from API.

**Out of scope:**
- Wire-up to Leads — 2.12. Wire-up to Custom Orders — 4.9.

## Files to touch
- `app/src/app/features/user/core/pipelines/*` (created)

## Plan
1. API service `getPipeline(key): Observable<PipelineOut>`.
2. Board: signals for stages and per-stage item buckets. cdk-drop-list per column; on drop emit `itemMoved({itemId, fromStage, toStage})`.
3. List: simple table with badge for stage; click to choose new stage.
4. Item rendering uses `<ng-template #itemTemplate let-item>` so callers (Leads/Orders) inject custom card content.

## Verification checklist
**Frontend:**
- dev demo route `/dev/pipeline-demo` (gated dev-only) shows the board with mock data; drag works.

## Self-check (10 rules)
- [ ] No imports from packs.
- [ ] Component is generic — no Lead-specific styling.

## Stop & report
Await "proceed" before Step 2.11.
