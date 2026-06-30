# Step 14 — Workflow canvas UI (node palette + drag-drop)

**Goal:** The marquee surface — Angular canvas at `/user/workflows/:id` where operators drag nodes from a palette, drop on the canvas, connect edges, and save. SVG-based; supports pan, zoom (0.25x-4x), grid snap, auto-layout, undo/redo. Per-node config drawer ships in Step 15.
**Status:** COMPLETED — `APP/package.json` gains `dagre@^0.8.5` + `@types/dagre@^0.7.52`. NEW `APP/src/app/features/user/core/workflows/canvas/node-type-registry.ts` ships the typed source of truth: 42 entries spanning the 1 trigger + 7 send + 8 record + 5 routing + 13 tagging/lifecycle + 8 flow-control catalogue. Each row carries `type`, `category`, `label`, `description`, `icon` (Lucide), `colorClass`, `inputPorts` (0 for trigger, 1 elsewhere), and `outputs[]` (port labels — `null` for sequential, `'yes'`/`'no'`/`'a'`/`'b'`/`'event_received'`/`'timeout'`/`'default'` for branched). `getNodeType(type)` + `NODE_TYPES_BY_KEY` + `PALETTE_SECTIONS` are exposed to consumers. NEW `canvas-state.service.ts` is a `@Injectable()` signal store: live `nodes` / `edges` / `selectedNodeId` / `zoom` / `pan` / `dirty` / `name` / `status` / `workflowId` plus a 50-entry undo/redo stack with `canUndo` + `canRedo` derived signals. Mutations (`addNode` / `deleteNode` / `duplicateNode` / `moveNode` / `moveNodeLive` / `updateNodeConfig` / `addEdge` / `deleteEdge`) snapshot the prior state before applying, set dirty, and (for `addEdge`) reject self-loops, duplicate triples, and targets whose node-type has `inputPorts=0`. `fitToView({width, height})` centres + zoom-fits the bounding box of all nodes within `[0.25, 4]`. NEW `node.component.ts` is one SVG `<g>`-host component rendering: selection halo, type-coloured rounded card, header (Lucide icon + name + validation red-dot when `config.__valid === false`), description, MoreVertical action menu with Duplicate / Disconnect / Delete (Disconnect cascades all incoming + outgoing edges through `CanvasStateService.deleteEdge`; Delete cascades the node via `deleteNode`), top input port circle (mouseup → `inputPortUp` event), bottom output ports distributed via `outputPortX(i, total)` (mousedown → `outputPortDown` event with the port label). NEW `edge.component.ts` draws a cubic-bezier `M S C S+dy, T-dy, T` between source's output port and target's input port; colour-codes labels (`yes`/`a`/`event_received` → emerald, `no`/`b`/`timeout` → pink, else slate); renders a centred pill badge for labelled edges; click → confirm-delete → `CanvasStateService.deleteEdge`. NEW `node-palette.component.{ts,html}` is the 300px-wide left rail with a search input filtering by label/type/description across `NODE_TYPES`, then six categorised sections (Triggers / Send / Record / Routing / Tagging+lifecycle / Flow control). Each item is `draggable="true"` and writes `text/workflow-node-type` MIME payload on `dragstart`. NEW `workflow-canvas.page.{ts,html}` is the orchestrator at `/user/workflows/:id` (existing) or `/user/workflows/new` (fresh draft): 3-column layout (palette · SVG canvas · 440px inspector drawer), header bar with name input, status badge, dirty indicator, Undo/Redo, Discard, Test-fire, Activate/Pause (status-dependent), and Save. Camera: pan via empty-space drag, zoom via Ctrl+Wheel toward the cursor (`p1 = point - (point - p0) * (z1/z0)`). Edge-drag: output-port mousedown opens a `pendingEdge` (signal) tracked through window-level mousemove, rendered as a dashed bezier; input-port mouseup commits via `state.addEdge`; mouseup anywhere else cancels. Drag-drop: `dragover` accepts the workflow MIME, `drop` reads the type + adds the node centred on the cursor in canvas coordinates (transform-aware via `toCanvasCoords`). Auto-layout: dynamic `import('dagre')` builds a `Graph` with `rankdir='TB'`, `nodesep=60`, `ranksep=100`, runs `layout()`, repositions every node, then calls `fitToView`. Auto-save: 30-second `setInterval` calls `save({silent:true})` when `dirty && status==='draft' && workflowId` (matches the templates editor pattern). `beforeunload` warns on dirty-navigate. Keyboard: Ctrl+Z undo, Ctrl+Shift+Z / Ctrl+Y redo, Ctrl+S save, Delete (on selected) deletes node. Right drawer is the Step-15 placeholder: renders the selected node's JSON + a stub note OR the test-fire trace (one row per hop with node_type + edge_label or skip_reason) OR an empty state. `WorkflowsApiService` extended with `WorkflowTestFireRequest` / `WorkflowTestFireStep` / `WorkflowTestFireResponse` types + `testFire(id, payload)` POST. Routes wired in `user.routes.ts`: `/user/workflows/new` (gated on `workflows.write`) and `/user/workflows/:id` (gated on `workflows.read`) both lazy-load the canvas page. Backend: `core/workflows/engine.py` extended with `DryRunStep` / `DryRunResult` dataclasses + `start_run(..., dry_run: bool = False) -> WorkflowRun | DryRunResult`. When `dry_run=True`, after the trigger-node lookup `start_run` delegates to NEW `_dry_walk(workflow, start_node_id)` which traces the graph in memory (200-hop cap, cycle detection emits `skip_reason='dry_run_cycle_detected'`, picks the first outbound edge at every fork since real conditions can't be evaluated, sets `outcome='goal_reached'` when the terminal node matches `workflow.goal_node_id`, else `'completed'`); no DB rows touched, no Celery dispatch. `core/workflows/router.py` adds `POST /workflows/{id}/test-fire` (`workflows.write`-gated, `WorkflowTestFireRequest`/`WorkflowTestFireResponse` Pydantic models with `extra='forbid'`) — resolves the workflow through the service, calls `engine.start_run(dry_run=True)`, projects the dataclass into the response model. NEW `API/tests/workflows/test_test_fire.py` ships 2 pytest cases: (1) `start_run(dry_run=True)` returns a `DryRunResult` with one step per node (`['t1', 's1', 'g1']`), `outcome='goal_reached'`, `error is None`, AND `engine._schedule_process_step` is NEVER called; (2) row counts on `tbl_workflow_runs` (workflow-scoped) and `tbl_workflow_step_runs` (cross-tenant) are identical before and after a `dry_run=True` call — pure in-memory. Pre-existing pin-test violations (56) exist in legacy helper files outside Step 14's scope (automation tasks/seeds/scheduler, workflows/engine commits inherited from Step 4, billing/tasks, etc.); none introduced by this step. Pytest run deferred per `feedback_pause_before_pytest.md`.
**Depends on:** Step 13 (workflows-api.service + list page CTAs route here).

---

## Scope

In-scope:

- `app/src/app/features/user/core/workflows/canvas/workflow-canvas.page.{ts,html}`:
  - URL: `/user/workflows/:id` (existing draft / active workflow) or `/user/workflows/new` (fresh draft).
  - Layout: left palette (300px), main canvas (flex-fill), right drawer (440px, opens on node click — Step 15 fills the body).
  - Header bar: workflow name input + status badge + Save / Activate / Pause / Discard / Run history / "Test fire" button.
  - Canvas: full-screen SVG with pan (drag empty space), zoom (Ctrl+wheel or pinch on touchpad), grid background, "fit to view" + "auto-layout" buttons in a floating control panel.

- `app/src/app/features/user/core/workflows/canvas/node-palette.component.{ts,html}`:
  - Categorized list of node types:
    - **Triggers**: every event in `event_catalog.py` (one node type — `trigger` — with the event_type selected in the config drawer).
    - **Send actions**: 7 (email / WA / SMS / FB / IG / push / Slack).
    - **Record actions**: 8 (update field x3, create task / note / appointment / quote / invoice).
    - **Routing actions**: 5 (round_robin / least_loaded / territory / skill / specific_user).
    - **Tagging + lifecycle**: 13 (add/remove tag, add/remove list, set score, mark converted, mark unsubscribed, block, archive, enroll workflow, enroll sequence, remove workflow, remove sequence, log internal note).
    - **Flow control**: 8 (wait, if/else, switch, ab_split, goal, wait_for_event, call_webhook, notify_user).
  - Each palette item: icon (Lucide), label, drag handle.
  - Drag from palette → drop on canvas → creates a node at drop coordinates.

- `app/src/app/features/user/core/workflows/canvas/node.component.{ts,html}`:
  - One component, type-agnostic. Renders the node as a rounded rectangle with:
    - Icon + name (operator-set label or default).
    - Top-right action menu (delete / duplicate / disconnect).
    - Input port (top edge) — single, accepts one incoming edge.
    - Output ports (bottom edge) — count depends on node type: 1 for sequential actions, 2 for if/else (yes/no), N for switch, 2 for wait_for_event (event_received/timeout), 2 for ab_split (a/b).
  - Click node → opens the right drawer with node-config (Step 15 fills it).
  - Validation marker — a tiny red dot in the corner when the node has unresolved validation issues (missing required config).

- `app/src/app/features/user/core/workflows/canvas/edge.component.{ts,html}`:
  - SVG path between two node ports. Cubic bezier (so edges aren't visually overlapping for parallel nodes).
  - Mid-edge label badge for branched edges (e.g. "yes" / "no" / "event_received" / "timeout").
  - Click edge → delete confirmation.

- `app/src/app/features/user/core/workflows/canvas/canvas-state.service.ts`:
  - Signal-based store for the live graph state — `nodes`, `edges`, `selected_node_id`, `zoom`, `pan_offset`.
  - Undo/redo stack — push every meaningful state change (max 50 entries).
  - Dirty flag — set on every change; Save flushes to backend + clears.
  - Auto-save: every 30 seconds when dirty + the workflow is in draft (mirrors templates editor's auto-save).

- Auto-layout — uses Dagre.js (peer dep added — `npm install dagre @types/dagre`). Operator clicks "Auto-layout"; the service re-positions all nodes top-to-bottom.

- Test fire — header button posts to a new `POST /api/v1/workflows/{id}/test-fire` endpoint that engine-runs a simulated event with a sample contact. Diagnostics output streams into the right drawer.

- "Test fire" backend endpoint (in router.py, gated on `workflows.write`): builds a synthetic event payload, calls `engine.start_run` against a `--dry-run` flag (Step 4 supports it via a context dict marker; if not yet, this step adds it as a tiny enhancement).

Out of scope:

- Per-node configuration drawer body (Step 15).
- Templates gallery (Step 16).
- Version history UI (Step 17).
- A/B test config UI (Step 18).
- Mobile-first responsive canvas — desktop-only for v1.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/workflows/canvas/workflow-canvas.page.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/node-palette.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/node.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/edge.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/canvas-state.service.ts` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/node-type-registry.ts` | **NEW** — typed registry of all 42 node types + their input/output port counts |
| `APP/src/app/features/user/user.routes.ts` | edit — lazy route to /user/workflows/:id and /user/workflows/new |
| `APP/package.json` | edit — add `dagre` + `@types/dagre` |
| `API/src/app/core/workflows/router.py` | edit — POST /workflows/{id}/test-fire endpoint |
| `API/src/app/core/workflows/engine.py` | edit — `dry_run=True` flag on start_run / process_step |
| `API/tests/workflows/test_test_fire.py` | **NEW** |

**~13 files. ~1100 lines.** Large step; the canvas + palette + state store + node/edge components all need to land together to be interactive.

## Plan

1. node-type-registry — 42 typed entries, the source of truth for what nodes exist + their port topology.
2. canvas-state.service with the signal store + undo/redo + dirty flag.
3. node + edge components — pure presentation.
4. node-palette + canvas page.
5. Auto-layout integration (Dagre.js).
6. Backend test-fire endpoint + engine dry_run flag.
7. Specs: load existing workflow + edit + save; drag-drop adds nodes; connect-edge wires nodes; auto-layout repositions.

## DB changes / migrations

None.

## Tests

6 Jest cases + 2 pytest cases:

- Loading a workflow with N nodes/edges renders all N+M elements.
- Drag from palette → drop on canvas → adds node to canvas-state + writes a Dirty signal.
- Connect two nodes → adds edge to canvas-state.
- Delete node → removes node + its edges.
- Undo restores previous state.
- Auto-layout re-positions nodes in topological order.
- (pytest) test-fire endpoint invokes `engine.start_run(dry_run=True)`.
- (pytest) test-fire with dry_run does NOT persist run rows.

## Smoke

```
1. /user/workflows/new → empty canvas, palette on left.
2. Drag "Trigger: lead.created" onto canvas → node lands at drop point.
3. Drag "Send action: send.email" below → node appears.
4. Connect trigger.output to send.email.input → edge appears with bezier curve.
5. Click send.email node → right drawer opens (empty in Step 14; Step 15 fills it).
6. Click "Save draft" → workflow persists.
7. Click "Test fire" → diagnostic output streams; no real send happens.
8. Click "Auto-layout" → nodes re-arrange top-to-bottom.
9. Ctrl+Z → undo last change.
10. Refresh page → workflow re-loads with the same graph.
```

## Risks

- Dagre.js is the only "heavy" frontend dep we'd add for this; vetted as standard for DAG layout (also used by VSCode, draw.io). Bundle adds ~30KB gzipped — acceptable.
- Touch/Pen support deferred to v2; v1 is desktop-mouse only.
- Workflow with 100+ nodes is the rare case; verify performance on a 50-node test workflow before declaring done.
- Test-fire could be misused to spam contacts; the `dry_run=True` flag MUST short-circuit every adapter call. Pytest covers it.

## Self-check (10 rules)
`core/workflows/` frontend + minor backend test-fire endpoint. ✓ org_id transparent via API. ✓ N/A custom fields. ✓ Static per-node-type forms (Step 15). ✓ Sidebar registered upstream. Permissions enforced server-side on test-fire. pack.yaml untouched. ✓ 13 files / ~1100 lines — large but justified (canvas + palette + state + node/edge + backend test-fire). Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 14 — Workflow canvas UI
Files: 13
Verify: canvas renders + persists; drag-drop adds nodes; edge connection works; auto-layout repositions; test-fire dry-runs without real sends.
Tests: 6 Jest + 2 pytest.
Awaiting "proceed".
```
