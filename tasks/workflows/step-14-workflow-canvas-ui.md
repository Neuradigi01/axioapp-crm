# Step 14 — Workflow canvas UI (node palette + drag-drop)

**Goal:** The marquee surface — Angular canvas at `/user/workflows/:id` where operators drag nodes from a palette, drop on the canvas, connect edges, and save. SVG-based; supports pan, zoom (0.25x-4x), grid snap, auto-layout, undo/redo. Per-node config drawer ships in Step 15.
**Status:** Pending
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
