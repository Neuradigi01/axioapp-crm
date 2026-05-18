# Step 2 — Frontend: stage editor popover

**Goal:** Build the reusable popover component admins click to rename, recolor, reorder, or delete a single pipeline stage. Self-contained — knows nothing about the kanban that hosts it; emits typed events the parent acts on.
**Track:** Lead Infrastructure
**Status:** Pending

---

## Scope

One new standalone Angular component (signal-based, OnPush, no NgModule) plus its template, dropped under the existing pipelines folder so it lives next to the board it'll be wired into.

### Public interface

| Member | Direction | Type | Purpose |
|---|---|---|---|
| `stage` | input (required) | `PipelineStage` | The row being edited. Drives the form's initial values and the "is this terminal?" branch. |
| `pipelineKey` | input (required) | `string` | Needed for the API calls. |
| `siblingCount` | input | `number` | Used to disable `→` when stage is already at the rightmost editable slot. |
| `saved` | output | `PipelineStage` | Emitted after a successful PATCH; parent re-fetches the pipeline (or merges in place). |
| `deleted` | output | `{stageId: string}` | Emitted after a successful DELETE with no card-relocation conflict. |
| `deleteBlocked` | output | `{stageId: string, cardsInStage: number}` | Emitted when DELETE returned 409 with `cards_in_stage > 0`. Parent opens the delete-confirm modal (step 4) to collect a relocation target and re-invoke. |
| `closed` | output | `void` | Emitted on Cancel / outside-click. |

### Layout

```
┌─────────────────────────┐
│ Edit stage              │
│                         │
│ Name                    │
│ [Qualified            ] │
│                         │
│ Colour                  │
│ [● ● ● ● ● ●] [#a855f7] │   ← preset swatches + free hex
│                         │
│ Position                │
│ [ ← ]      [ → ]        │   ← hidden if terminal
│                         │
│ ───────────────────     │
│ 🗑 Delete this stage    │   ← hidden if terminal
│                         │
│            [Cancel][Save]│
└─────────────────────────┘
```

For `stage.is_won` or `stage.is_lost`:

- Position buttons hidden.
- Delete link hidden.
- A small notice rendered below the colour row: `ⓘ This stage marks leads as won/lost — name and colour only.`

### Behaviour

| Action | Wire-up |
|---|---|
| User edits name / colour | Held in local signal state. Save button enables when form is dirty + valid. |
| Click `←` | Computes `display_order - 1`; clamps at `0`. Sets dirty. |
| Click `→` | Computes `display_order + 1`; clamps at `siblingCount - 1`. Sets dirty. |
| Click Save | `PipelinesApiService.updateStage(pipelineKey, stage.id, payload)` with **only changed fields** (PATCH semantics). On 200, emit `saved` with the response and close. On error, surface the message from `extractApiError` near the Save button; popover stays open. |
| Click Delete | `PipelinesApiService.deleteStage(pipelineKey, stage.id)` (no relocation target on first try). On 204, emit `deleted` and close. On 409 with `cards_in_stage`, emit `deleteBlocked`; **do NOT close** — parent will open the confirm modal then either re-invoke delete-with-target or close this popover. |
| Cancel / outside click | Emit `closed`. No API call. |

### Permission gating

The popover itself does not check permissions — the parent only renders it if `canManage()` is `true`. That keeps this component reusable from anywhere that already gated visibility.

### Validation

| Field | Rule |
|---|---|
| `name` | required; trimmed; 1–128 chars (matches backend `max_length=128`) |
| `color` | optional; if provided must be a 3/4/6/8-char hex starting with `#`; preset swatches always valid |
| `display_order` | clamped client-side; backend is also defensive |

## Why no backend changes

The PATCH endpoint and `PipelinesApiService.updateStage()` already exist. This step is pure UI on top.

The DELETE endpoint is added in **Step 1**; this step depends on Step 1 having shipped a new method on the API service:

```ts
deleteStage(pipelineKey: string, stageId: string, moveLeadsTo?: string): Observable<void>
```

That method addition lives in the same `pipelines-api.service.ts` and is small enough to fold into Step 1 or do here at the top of this step. **Decision: add it here**, alongside the new component, so Step 1 stays purely backend.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/pipelines/stage-editor-popover.component.ts` | NEW. ~150 lines. |
| `app/src/app/features/user/core/pipelines/stage-editor-popover.component.html` | NEW. ~80 lines of Tailwind markup. |
| `app/src/app/features/user/core/pipelines/pipelines-api.service.ts` | add `deleteStage(pipelineKey, stageId, moveLeadsTo?)` method (~12 lines) |

**3 files. No backend changes (Step 1 owns those).**

## Tailwind / styling

Match the existing popover idiom used elsewhere in `/user/core/...`. Reference `https://furniture-crm-alpha.vercel.app/user/core/leads` for spacing / colour-swatch sizing before writing the template. No new tokens; reuse `@core` tokens / utility classes already in the project.

## Tests

Component test `stage-editor-popover.component.spec.ts`:

- Renders inputs prefilled from `stage`.
- Save button disabled until form is dirty.
- Editing name + clicking Save calls `updateStage` with only `{name}`; emits `saved` on success.
- `←` reduces `display_order` and clamps at 0.
- `→` increases `display_order` and clamps at `siblingCount - 1`.
- Terminal stage (`is_won=true`): position buttons + delete link not rendered; notice shown.
- Delete click on non-terminal with no leads: emits `deleted`.
- Delete click that returns 409 with `cards_in_stage=3`: emits `deleteBlocked` with `{stageId, cardsInStage: 3}`; does not close.
- Cancel: emits `closed`.

## Smoke

```
cd app && npm run build      # ng build, type-check clean
# user starts ng serve themselves; manual smoke deferred to step 4 wire-up
```

This step does not wire the component into any page — that happens in **Step 4**. Standalone unit tests are the verification here.

## Rollback

Revert the 3 files. No DB state change. No backend change.
