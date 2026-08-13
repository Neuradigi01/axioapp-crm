# Step 14 — Frontend node components (config-on-node) + test dialog

**Goal:** Ship one Angular component per node type (23 total) so operators can configure each node inline on the canvas (Pabbly-style config-on-node), plus the test-bot chat simulator dialog.
**Depends on:** Step 13
**Status:** Pending

## Scope

**In-scope**
- 23 node components under `builder/nodes/*.node.ts` — one per node type from `node-type-registry`.
- `node.base.ts` — shared header (title + duplicate + delete icons), selection outline, port rendering, drag-to-move.
- Config-on-node UX: each node renders its own form fields directly on the canvas (mirrors Pabbly).
- Implicit output ports on Text Button / Media Button (one per button, dynamic count) and List (one per row).
- Save-target picker widget (used by Ask-* + Set Custom Field nodes) — consumes `GET /chatbots/save-targets`.
- `test-bot-dialog.component` — chat simulator: text input → simulates inbound → renders bot response bubbles → shows diagnostics side panel. Dry-run enforced.
- Reply-button editor sub-component (used by Text Button + Media Button).
- Message editor with WA formatting hints, char counter, `{{variable}}` autocomplete.

**Out of scope**
- Version history drawer — Step 15.
- Import/Export JSON dialog — Step 15.

## Files to touch

- `APP/src/app/features/user/core/chatbots/builder/nodes/node.base.ts` (created)
- `APP/src/app/features/user/core/chatbots/builder/nodes/trigger-card.node.ts` (created — the top-of-canvas summary card)
- One component file per node type (~23 files) under `builder/nodes/`
- `APP/src/app/features/user/core/chatbots/builder/nodes/save-target-picker.component.ts` (created)
- `APP/src/app/features/user/core/chatbots/builder/nodes/message-editor.component.ts` (created)
- `APP/src/app/features/user/core/chatbots/builder/nodes/reply-button-editor.component.ts` (created)
- `APP/src/app/features/user/core/chatbots/builder/test-dialog/test-bot-dialog.component.ts` (created)
- `APP/src/app/features/user/core/chatbots/builder/test-dialog/test-bot-dialog.component.html` (created)

**Note:** this is the largest step of the track. If any of the individual node components + shared helpers push the total over 400 lines / 15 files, split into two sub-steps at implementation time:
- **Step 14a:** Messages + Ask-* + shared editors (14 components).
- **Step 14b:** Actions + CRM extras + AI stubs + test dialog (12 components).

## Plan

1. `node.base.ts` — abstract component with `@Input() nodeId`, selection outline, header (title + duplicate/delete icons), port markers (input on left, output(s) on right per registry topology).
2. Each concrete `*.node.ts` extends `node.base.ts`:
   - Renders `<node-base>` wrapper + its own config form.
   - Uses `builder-canvas.service` to read + patch its own config.
   - Ports are rendered by base component based on registry `outputs` metadata (single | labeled | dynamic).
3. `save-target-picker` — dropdown with `entity` selector + field selector; loads via `chatbots-api.service.listSaveTargets(entity)`; caches per (org, entity). Sensitive fields absent from the list (server-side enforced).
4. `message-editor` — textarea with:
   - Char counter (1024 WA, 4000 email; 0 = no limit).
   - `{{variable}}` autocomplete popup with `contact.*`, `lead.*`, `answers.*` categories.
   - WA formatting toolbar (bold/italic/strike/monospace) inserts markers.
5. `reply-button-editor` — reorderable list of button labels (max 3); "Add button" button; validation.
6. `test-bot-dialog`:
   - Modal opens from top-bar "Test bot" button.
   - Left panel: chat simulator (send text messages).
   - Right panel: diagnostics log (each event: trigger.matched, node.executed, node.parked, node.resumed, save.write, cap.hit, run.canceled).
   - Sends test text via `POST /chatbots/:id/test-fire` with `dry_run=true`.
   - Renders bot outbound bubbles as they arrive; polls or listens via SSE (existing infra).
   - "Reset" button clears the test run.
7. Prettier + eslint clean per memory.

## DB changes / migrations

None.

## Tests to add

Frontend unit tests (Karma):
- `node.base.spec.ts` — header renders; port count matches registry.
- Per-node spec files — each config form saves back to canvas service with valid payload.
- `save-target-picker.spec.ts` — populates entities; excludes sensitive fields (mock backend); collision key rejected inline.
- `message-editor.spec.ts` — char counter; variable autocomplete.
- `test-bot-dialog.spec.ts` — dry-run flag sent; diagnostics rendered from mock SSE.

Manual:
- Build a real 6-node bot end-to-end: Trigger → Text Button → Ask Question → Ask Question → Set Custom Field → Handoff.
- Test-fire the bot with three different scripted inbounds; verify all three take the correct paths.

## Verification checklist

**Backend** — N/A (all backend endpoints exist by now).

**Frontend**
- [ ] Every node type from the registry has a matching component file.
- [ ] Config-on-node — clicking a node does NOT open a right drawer; the fields are directly on the node face.
- [ ] Save-target picker never shows `role`, `owner_id`, `balance`, `subscription_tier`.
- [ ] Test-bot dialog runs a 3-question flow to completion.
- [ ] All new components use signals + typed reactive forms + `@if/@for` control flow.
- [ ] Prettier + eslint pass on all new files.

**Code review**
- [ ] No hardcoded field list in the picker — all data from the API.
- [ ] Node components deep-clone config before patching to avoid signal-mutation gotchas.
- [ ] Test dialog handles error responses gracefully (`ai_not_configured`, `session_expired`, `question_invalid`).

## Self-check (10 rules)

- [ ] Frontend `core/` didn't import `packs/`
- [ ] Sidebar / permissions correct
- [ ] Tailwind only
- [ ] Under 15 files, under ~500 lines per split (14a / 14b)
- [ ] Zero TODOs
- [ ] Reuse — extended existing `builder-canvas.service`, no duplication of state

## Stop & report

Report screenshots of at least 6 different configured nodes on the canvas (Trigger, Text Button, Ask Question, Set Custom Field, Handoff, Connect Flow) + a screenshot of the test-bot dialog after a 3-question run + a video/gif if feasible. Run `npx --no-install prettier --write` on all touched files before reporting. Await "proceed".
