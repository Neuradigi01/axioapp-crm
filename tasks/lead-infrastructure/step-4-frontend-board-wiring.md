# Step 4 — Frontend: wire stage-management affordances into the kanban

**Goal:** Surface the editor popover (Step 2) and add-stage popover (Step 3) on the Leads kanban, plus build the delete-confirm modal that handles the "stage has leads in it" branch. Permission-gated end-to-end so Sales Executives see a read-only board.
**Track:** Lead Infrastructure
**Status:** Pending

---

## Scope

Three pieces:
1. **One new component** — the delete-confirm modal that opens when DELETE returned 409 with `cards_in_stage > 0`.
2. **Modify the existing** `pipeline-board.component.{ts,html}` to render pencil icons + an `+ Add stage` button + popover/modal anchors, all gated on `pipelines.manage`.
3. **Resolve the permission source** — find where the Angular app exposes the current user's permission list and wire it in. If no signal/service exists today, add a thin reader. No new auth plumbing.

### 1. New component: delete-stage-confirm modal

Renders centred on the page when DELETE returned 409. Asks the admin to pick a relocation target before re-invoking delete with the chosen key.

#### Public interface

| Member | Direction | Type | Purpose |
|---|---|---|---|
| `stage` | input (required) | `PipelineStage` | The stage being deleted. Shown in the prompt. |
| `cardsInStage` | input (required) | `number` | The lead count returned by the failed delete. Shown verbatim. |
| `candidateStages` | input (required) | `PipelineStage[]` | All other stages in the same pipeline (excluding the one being deleted). The dropdown lists them in `display_order`. |
| `confirmed` | output | `{moveLeadsTo: string}` | Emitted when admin clicks Delete. Parent re-invokes DELETE with this target. |
| `cancelled` | output | `void` | Emitted on Cancel / outside-click. |

#### Layout

```
┌────────────────────────────────────────┐
│ Delete "Qualified"?                    │
│                                        │
│ ⚠  3 leads are currently in this stage.│
│    Move them to:                       │
│                                        │
│    ┌────────────────────────────────┐  │
│    │ Contacted                  ▼   │  │
│    └────────────────────────────────┘  │
│                                        │
│ This cannot be undone.                 │
│                                        │
│              [Cancel] [Delete stage]   │
└────────────────────────────────────────┘
```

Default selection: the stage immediately before the one being deleted in `display_order` (e.g. deleting "Qualified" defaults to "Contacted"). Falls back to the first candidate if the deleted stage was already at position 0.

### 2. Modify pipeline-board

Pencils on every column header (rendered conditionally on `canManage()`); `+ Add stage` button at the right end of the columns row; overlay slots for the three popovers/modal.

#### Visual delta

```
SALES REP (no `pipelines.manage`):

┌─────────────────────┬─────────────────────┬─────────────────────┐
│ ● New           4   │ ● Contacted     7   │ ● Qualified     3   │
└─────────────────────┴─────────────────────┴─────────────────────┘

ADMIN (has `pipelines.manage`):

┌─────────────────────┬─────────────────────┬─────────────────────┬─────────────┐
│ ● New        4   ✎  │ ● Contacted  7   ✎  │ ● Qualified  3   ✎  │ + Add stage │
└─────────────────────┴─────────────────────┴─────────────────────┴─────────────┘
```

#### New signals on the board component

```ts
canManage         = computed(() => userPerms().includes('pipelines.manage'));
editingStage      = signal<PipelineStage | null>(null);
addingPopoverOpen = signal(false);
deleteConfirm     = signal<{ stage: PipelineStage; cardsInStage: number } | null>(null);
```

#### Event handlers

| User action | Handler | Result |
|---|---|---|
| Click ✎ on a column header | `openEditor(stage)` | `editingStage.set(stage)` |
| Click `+ Add stage` | `openAdd()` | `addingPopoverOpen.set(true)` |
| Editor emits `saved` | `onStageSaved()` | Re-fetch pipeline via existing `fetchPipeline(pipelineKey)`; close popover |
| Editor emits `deleted` | `onStageDeleted()` | Re-fetch pipeline; close popover |
| Editor emits `deleteBlocked({stageId, cardsInStage})` | `onDeleteBlocked(...)` | `deleteConfirm.set({stage, cardsInStage})`; keep editor closed |
| Editor emits `closed` | `onEditorClosed()` | `editingStage.set(null)` |
| Add popover emits `created` | `onStageCreated()` | Re-fetch pipeline; close popover |
| Add popover emits `closed` | `onAddClosed()` | `addingPopoverOpen.set(false)` |
| Delete-confirm emits `confirmed({moveLeadsTo})` | `onDeleteConfirmed(...)` | Call `deleteStage(pipelineKey, stage.id, moveLeadsTo)`; on 204 re-fetch pipeline; close modal |
| Delete-confirm emits `cancelled` | `onDeleteCancelled()` | `deleteConfirm.set(null)` |

#### Re-fetch is idempotent

The board already has an `effect` that rebuilds buckets when stages change. Re-fetching the pipeline causes the stages signal to update, which causes that effect to run, which causes the columns to re-render in their new shape. No manual sync needed.

### 3. Permission source — to be resolved at start of this step

First action: `grep -r 'permissions' app/src/app/core/services` to find the existing user/auth service. Expected locations:

- `app/src/app/core/services/auth/...`
- `app/src/app/core/services/user/...`
- An `inject(AuthService).currentUser$` or signal

The board reads from whichever service exists. If permissions are returned as part of `/users/me` (likely), they're already in the user signal — just consume it. If not exposed, add a one-line getter on the existing user service; **do not** create a new service for this.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/pipelines/delete-stage-confirm.component.ts` | NEW. ~90 lines. |
| `app/src/app/features/user/core/pipelines/delete-stage-confirm.component.html` | NEW. ~60 lines. |
| `app/src/app/features/user/core/pipelines/pipeline-board.component.ts` | MODIFY. Add the 4 signals + 8 handlers + permission reader; expose `canManage` to the template; import the three new components. ~80 lines diff. |
| `app/src/app/features/user/core/pipelines/pipeline-board.component.html` | MODIFY. Add `@if (canManage())` pencil button on each `<header>`, `+ Add stage` cell at the end of the columns row, and overlay anchors for the editor / add / delete-confirm overlays at the bottom of the template. ~40 lines diff. |
| `app/src/app/features/user/core/services/<auth-or-user>.service.ts` (existing) | possibly extend to expose a permission signal if not already there. **At most a one-line getter.** |

**4 files modified or created, plus possibly 1 small getter addition.** Within the < 10 files / < 400 lines per-step rule.

## Tailwind / styling

Match the existing kanban look. Reference `https://furniture-crm-alpha.vercel.app/user/core/leads` for the pencil placement and `+ Add stage` cell sizing before writing the markup. No new utility classes.

## Tests

`pipeline-board.component.spec.ts` (extend existing tests):

- Renders pencils on every column header when `canManage()` is `true`.
- Does NOT render pencils when `canManage()` is `false`.
- Renders `+ Add stage` button only when `canManage()` is `true`.
- Click ✎ opens the editor popover with the correct stage.
- Click `+ Add stage` opens the add popover.
- Editor's `saved` triggers a re-fetch.
- Editor's `deleteBlocked` opens the delete-confirm modal with the correct stage + count; editor closes.
- Delete-confirm's `confirmed` triggers `deleteStage(... , moveLeadsTo)`; on 204 the modal closes and pipeline re-fetches.

`delete-stage-confirm.component.spec.ts`:

- Default-selected target is the stage immediately before the one being deleted.
- If deleted stage was at `display_order=0`, defaults to first candidate.
- `confirmed` emits with the chosen target's key.
- `cancelled` emits on Cancel button.

## Smoke

```
cd app && npm run build      # ng build, type-check clean
```

**Will not start `ng serve`** — user does that themselves.

Manual smoke after user starts the dev server:

- Login as `admin@core-demo.local` → navigate to `/user/core/leads` → see pencils on every column + `+ Add stage` at the end.
- Click ✎ on "Qualified" → editor popover opens → change name to "Vetted" → Save → column header renders "Vetted".
- Click `+ Add stage` → name "Demo Scheduled", select "After: Contacted", Add → new column appears at position 3, others shifted right.
- Click ✎ on "Demo Scheduled" → click "Delete this stage" (it has no leads) → column disappears.
- Drag a lead from "New" to "Vetted" → still works (existing `move_card` flow untouched).
- Click ✎ on "Vetted" again → click "Delete this stage" → since leads are in it now, delete-confirm modal opens → pick "Contacted" → Delete → modal closes, all "Vetted" leads now in "Contacted", column gone.
- Click ✎ on "Won" → name + colour fields visible, position buttons + delete link hidden, notice rendered.
- Logout, log back in as `employee@core-demo.local` → `/user/core/leads` shows the same kanban with NO pencils and NO `+ Add stage` button.

## Rollback

Revert the 4 (or 5) files. No DB state change. No backend change.

## After this step

Lead Infrastructure track complete. The Leads page is genuinely self-customisable for any tenant — they can mould the funnel to their business without a developer.
