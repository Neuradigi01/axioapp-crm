# Step 3 — Frontend: add-stage popover

**Goal:** Build the reusable popover admins click to create a new pipeline stage at a chosen insertion point. Self-contained, mirrors the shape of the editor popover from Step 2.
**Track:** Lead Infrastructure
**Status:** Pending

---

## Scope

One new standalone Angular component (signal-based, OnPush, no NgModule) plus its template.

### Public interface

| Member | Direction | Type | Purpose |
|---|---|---|---|
| `pipelineKey` | input (required) | `string` | Needed for the POST call. |
| `stages` | input (required) | `PipelineStage[]` | Populates the "Insert after" dropdown. Filters out terminal stages from being the insertion anchor (you can't insert *after* "Lost" — it stays terminal). |
| `created` | output | `PipelineStage` | Emitted after a successful POST with the new stage returned from the backend. |
| `closed` | output | `void` | Emitted on Cancel / outside-click. |

### Layout

```
┌─────────────────────────────┐
│ Add stage                   │
│                             │
│ Name                        │
│ [                         ] │
│                             │
│ Colour                      │
│ [● ● ● ● ● ●] [#______]     │
│                             │
│ Insert                      │
│ ┌─────────────────────────┐ │
│ │ After: Contacted     ▼  │ │   ← dropdown; defaults to "(at the end)"
│ └─────────────────────────┘ │
│                             │
│         [Cancel] [Add stage]│
└─────────────────────────────┘
```

### Dropdown options

The "Insert" dropdown lists, in order:
- `(at the end)` — the default; results in no `after_stage_key` in the request payload
- Every non-terminal stage in `display_order` ascending: "After: New", "After: Contacted", "After: Qualified", "After: Proposal"

Terminal stages (`is_won`, `is_lost`) are deliberately omitted as insertion anchors. The backend would not reject inserting after Won/Lost, but UX-wise it's wrong: those rows always stay at the end.

### Behaviour

| Action | Wire-up |
|---|---|
| User types name | Held in local signal. `Add stage` button enables when name is non-empty (after trim). |
| User picks colour | Either a preset swatch or types a free hex; both update the signal. |
| User picks insertion anchor | Stored as `afterStageKey` signal; `null` means "at the end". |
| Click `Add stage` | POST `/api/v1/pipelines/{key}/stages` with `{name, color?, after_stage_key?}`. On 201, emit `created` with the response and close. On 422 (key collision), surface the message near the name field; stay open. On 403, surface a generic "you don't have permission" and close — defensive only; parent shouldn't render this popover for non-admins. |
| Cancel / outside click | Emit `closed`. No API call. |

### Default colour

If the user does not pick a colour, send `color: undefined` and let the backend default the column to `null` — the kanban already renders a neutral grey bar for stages without a colour ([pipeline-board.component.ts:146](../../APP/src/app/features/user/core/pipelines/pipeline-board.component.ts)).

### Validation

| Field | Rule |
|---|---|
| `name` | required; trimmed; 1–128 chars |
| `color` | optional; if provided, must match `#[0-9a-fA-F]{3,8}` |
| `after_stage_key` | optional; if provided must exist in `stages` input — UI guarantees this via the dropdown |

## API service addition

Add a method to the existing `PipelinesApiService`:

```ts
createStage(
  pipelineKey: string,
  payload: { name: string; color?: string; after_stage_key?: string }
): Observable<PipelineStage>
```

POSTs to `/pipelines/{pipelineKey}/stages`. Returns the new stage row.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/pipelines/add-stage-popover.component.ts` | NEW. ~120 lines. |
| `app/src/app/features/user/core/pipelines/add-stage-popover.component.html` | NEW. ~70 lines. |
| `app/src/app/features/user/core/pipelines/pipelines-api.service.ts` | add `createStage(pipelineKey, payload)` method (~10 lines) |

**3 files. No backend changes (Step 1 owns those).**

## Tests

Component test `add-stage-popover.component.spec.ts`:

- Renders empty form; Add button disabled.
- Typing a name enables the Add button.
- "Insert" dropdown lists `(at the end)` first, then non-terminal stages in `display_order`. Terminal stages (`is_won`/`is_lost`) not present.
- Click Add with name only → calls `createStage` with `{name}`, no `color`, no `after_stage_key`; emits `created` on success.
- Click Add after selecting "After: Contacted" → payload includes `after_stage_key: "contacted"`.
- 422 from backend with `key collision` message → message rendered near name field; popover stays open.
- Cancel emits `closed`.

## Smoke

```
cd app && npm run build      # ng build, type-check clean
# user starts ng serve themselves; manual smoke deferred to step 4 wire-up
```

Not yet wired into any page — that happens in **Step 4**. Unit tests are the verification here.

## Rollback

Revert the 3 files. No DB state change. No backend change.
