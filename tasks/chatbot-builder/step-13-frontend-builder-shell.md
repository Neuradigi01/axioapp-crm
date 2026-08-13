# Step 13 — Frontend builder shell + palette (Messages / Actions tabs) + node registry

**Goal:** Land the Pabbly-style builder page shell at `/user/chatbots/:id/edit` — top bar, canvas with pan/zoom, palette with Messages/Actions tabs, node-type registry, autosave, undo/redo. No node components yet (Step 14).
**Depends on:** Step 12
**Status:** Pending

## Scope

**In-scope**
- Route `/user/chatbots/:id/edit`.
- `builder.component` — top bar (bot name, Draft/Live toggle, Save, undo/redo, Test bot, version history), palette + canvas layout matching the mockup at `tasks/chatbot-builder/mockup.html`.
- `builder-canvas.service` — signal-based state: nodes, edges, selection, dirty flag, undo/redo stack, autosave dirty timer (30s per existing workflows pattern).
- `palette.component` — Messages / Actions tabs with underline indicator; grid tiles for each node type; drag-to-canvas support.
- `node-type-registry.ts` — SINGLE source of truth for node metadata: type key, label, icon, category (message/action/crm-extra), palette tab, ports topology, default config, channel-support matrix. Consumed by both palette and node components (Step 14).
- Trigger summary card at top of canvas (always present, opens `trigger-config.modal` when clicked).
- Zoom + pan controls; auto-layout button; fit-to-screen.

**Out of scope**
- Node components themselves — Step 14.
- Test bot dialog — Step 14.
- Version history drawer — Step 15.

## Files to touch

- `APP/src/app/features/user/core/chatbots/builder/builder.component.ts` (created)
- `APP/src/app/features/user/core/chatbots/builder/builder.component.html` (created)
- `APP/src/app/features/user/core/chatbots/builder/builder-canvas.service.ts` (created)
- `APP/src/app/features/user/core/chatbots/builder/palette/palette.component.ts` (created)
- `APP/src/app/features/user/core/chatbots/builder/palette/node-tile.component.ts` (created)
- `APP/src/app/features/user/core/chatbots/shared/node-type-registry.ts` (created)
- `APP/src/app/features/user/core/chatbots/builder/trigger-modal/trigger-config.modal.ts` (created — opens for the trigger card; keywords/regex/channel/priority editor)
- `APP/src/app/features/user/core/chatbots/chatbots.routes.ts` (modified — add `:id/edit` route)

## Plan

1. `node-type-registry.ts` — export a const array of `NodeTypeMeta` items covering all 23 node types (7 Messages + 12 Actions + 4 CRM extras) plus the always-present Trigger summary card. Fields:
   ```ts
   type NodeTypeMeta = {
     type: string;                     // e.g. "text_button"
     label: string;                    // "Text Button"
     icon: string;                     // emoji or lucide name
     category: "message" | "action" | "crm";
     paletteTab: "messages" | "actions";
     supports: { wa_cloud: boolean; wa_baileys: "native" | "fallback" | "none"; email: "native" | "fallback" | "none" };
     inputs: 1 | 0;                    // trigger has 0
     outputs: "single" | "labeled" | "dynamic";  // labeled = fixed set (answered/invalid/timeout), dynamic = one per button
     defaultConfig: Record<string, unknown>;
   };
   ```
2. `palette.component` — reads registry; groups by `paletteTab`; renders 2-column grid of `node-tile`; drag events dispatch to canvas service.
3. `builder.component` layout — grid: sidebar (52px) + palette (280px) + canvas (flex) — matches mockup.
4. `builder-canvas.service`:
   - Signals: `nodes()`, `edges()`, `selectedNodeId()`, `dirty()`, `saving()`.
   - Methods: `addNode(type, position)`, `updateNode(id, config)`, `deleteNode(id)`, `addEdge(sourceId, sourcePort, targetId)`, `deleteEdge(id)`, `undo()`, `redo()`.
   - Autosave: dirty timer flushes to `PATCH /chatbots/:id` every 30s if dirty. Manual Save button flushes immediately.
   - Serializer round-trips graph JSON with backend schema (Case: semantically equal, not byte-identical — T48 clarification).
5. Trigger card — special node rendered at fixed top-left; not draggable-in from palette (per Decision §3); click → `trigger-config.modal` opens; modal edits `bot.trigger_config` (keywords chips, regex toggle, channel picker, priority slider).
6. Draft/Live toggle in top bar — flips `bot.status` via `POST /chatbots/:id/publish` or `/pause`; requires `chatbots.publish` permission (button disabled otherwise with tooltip).
7. Undo/redo — 50-step history (memory bounded).

## DB changes / migrations

None.

## Tests to add

Frontend unit tests (Karma):
- `builder-canvas.service.spec.ts` — add/update/delete node + edge; undo/redo correctness; dirty flag flips on mutation.
- `palette.component.spec.ts` — tabs switch; tiles render one per registry entry.
- `node-type-registry.spec.ts` — every type declared has all required metadata fields (uses a schema check).
- `trigger-config.modal.spec.ts` — keyword chip add/remove; regex toggle; save calls API with correct payload.

Manual:
- Round-trip a bot graph (save, reload, save again — resulting graph JSON should be semantically identical).
- Autosave test: leave the tab open, modify, wait 30s → save fires.
- Undo/redo across 20 mutations.

## Verification checklist

**Backend** — N/A.

**Frontend**
- [ ] `/user/chatbots/:id/edit` loads with an existing bot's graph.
- [ ] Palette Messages / Actions tabs switch correctly.
- [ ] Drag from palette places a node on the canvas at drop point.
- [ ] Trigger modal opens on click, saves back to bot.
- [ ] Save button green when dirty, muted when clean.
- [ ] Ctrl+Z / Ctrl+Shift+Z work.
- [ ] Prettier + eslint clean.

**Code review**
- [ ] Registry is a plain data export — no logic in the file.
- [ ] Canvas service state is signal-based (per Angular 20+ stack rule).
- [ ] No PrimeNG / Material additions.
- [ ] Lucide icons registered per memory `feedback_lucide_icon_registry.md`.

## Self-check (10 rules)

- [ ] Frontend `core/` didn't import `packs/`
- [ ] Sidebar / permissions correct
- [ ] Tailwind only
- [ ] Under 10 files, under 400 lines per file (split if needed)
- [ ] Zero TODOs

## Stop & report

Report a screenshot of the empty builder with the palette and trigger card, one screenshot of a mid-build state with 3-4 nodes and edges, and the graph JSON diff before/after a save round-trip. Await "proceed".
