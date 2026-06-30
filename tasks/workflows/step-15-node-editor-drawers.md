# Step 15 — Node editor drawers (per-node config)

**Goal:** The right-side drawer that pops when the operator clicks a node. Renders a typed form per node type so the operator can configure event_type (for triggers), template_id + recipient (for sends), field path + value (for record updates), pool spec (for routing), conditions AST (for branches), etc.
**Status:** COMPLETED — NEW `APP/src/app/features/user/core/workflows/canvas/editors/editor-contract.ts` ships the typed contract: `NodeEditorContract` documentation interface (`[node]` input + `(configChange)` / `(validityChange)` outputs), `ConditionNode` AST union (`leaf` / `and` / `or` / `not`), `ConditionOp` enum (14 ops — `eq`/`neq`/`gt`/`gte`/`lt`/`lte`/`in`/`not_in`/`contains`/`starts_with`/`ends_with`/`is_empty`/`is_not_empty`/`changed_to`), `CONDITION_OPS` UI label list, `emptyAndGroup()` / `emptyLeaf()` factories, `VariablePath` + `VariableGroup` types, `ALWAYS_AVAILABLE` group (`now`, `org.name`, `actor.email`), 7 context groups (`Contact`/`Lead`/`Appointment`/`Task`/`Quote`/`Invoice`/`Conversation`), `VARIABLE_GROUPS_BY_EVENT_PREFIX` map keyed on `lead.`/`contact.`/`appointment.`/`task.`/`quote.`/`invoice.`/`email.`/`whatsapp.`/`sms.`, `variableGroupsForEvent(eventType)` selector, `EVENT_TYPES` catalogue (27 events with `label`/`description`/`waitable` flag spanning lead+contact+appointment+task+conversation+billing lifecycle), `WAITABLE_EVENT_TYPES` precomputed filter, `EMAIL_RECIPIENTS` / `PHONE_RECIPIENTS` / `SEND_CATEGORIES` option lists. NEW `conditions-builder.component.{ts,html}` is the shared AST tree: single recursive component (`*ngTemplateOutlet` with `path: number[]` index addressing), supports adding root + child leaves, toggling AND↔OR, wrapping in NOT (and unwrapping), per-leaf path/op/value editing with `<datalist>` autocomplete from `suggestedPaths`, immutable patch via `replaceAt(path, next | null)` so undo/redo snapshots stay tidy, `is_empty`/`is_not_empty` hide the value input. NEW `variable-picker.component.{ts,html}` is the context-aware browser: search across `path`/`label`/`description`, groups collapse when filtered to empty, click → emits `{{path}}` mustache for caret insertion in the parent textarea. NEW `node-editor.component.{ts,html}` is the dispatcher: takes `[node]` + emits `(close)`, header collects label input + Duplicate / Disconnect / Delete actions, `editorKey()` computed signal maps every `node.type` to one of 26 sub-editor keys (42 → 26 mapping: trigger=1, send=7, record.update_*=1, record.create_*=5, routing=1, tagging covers 5 tag/list/score=1, lifecycle covers 4 markers=1, enroll covers 4 enroll/remove=1, 8 flow-control=8; `flow_control.log_internal_note` aliased to `create_note`), 26 typed editors imported and dispatched via `@switch`. Sub-editor IO bridge: `(configChange)` patches merge through `state.updateNodeConfig(nodeId, patch)`; `(validityChange)` stamps `__valid` on `node.config` so the SVG node card lights its red dot. NEW `trigger-editor.component` renders event_type picker (27 options + description tooltip), re-enrollment-rule (once/daily/never), conditions-builder bound to context groups from `variableGroupsForEvent(eventType)`, valid when `event_type` set. NEW 7 send editors: `send-editor-shared.ts` exports `readSendState(node)` + `sendIsValid(state)` so the thin components share the validity contract. `send-email-editor` (template_id + recipient picker from `EMAIL_RECIPIENTS` with custom-path fallback + category + tracking flags `track_opens`/`track_clicks`); `send-whatsapp-editor` (Meta-approved templates only via copy on the form); `send-sms-editor` (DLT-template hint for IN tenants); `send-fb-editor` + `send-ig-editor` (PSID/IGID recipients); `send-push-editor` (target user picker — workflow.owner/lead.owner/contact.assigned_to); `send-slack-editor` (`slack_channel` instead of recipient — channel name like `#crm-alerts`). NEW 5 create editors: `create-task` (title/description/assignee/due_in_days), `create-note` (entity contact/lead + body), `create-appointment` (title/assignee/schedule_in_hours/duration_minutes), `create-quote` (template_id/amount/expires_in_days/send_email), `create-invoice` (template_id/amount/due_in_days). NEW `update-field-editor` covers all 3 `record.update_*` types — entity inferred from node.type, operator picks `field_key` (system or `custom_data.<key>`), `value_source` (literal/trigger_payload/context), and `value`. NEW `routing-editor` covers all 5 routing modes — mode chip from node.type, `pool_type` (role/team/explicit), `pool_value` text input, target attachment (lead.assigned_to / contact.assigned_to), fallback resolver (workflow.owner / leave_unassigned / skip), `specific_user_id` UUID input for the specific-user variant. NEW `tagging-editor` covers 5 nodes (tag.add/remove + list.add/remove + lifecycle.set_score) — branches on node.type to render tag name OR list UUID OR score-mode-and-value inputs. NEW `lifecycle-editor` covers 4 marker types (mark_converted with `conversion_reason` won/qualified/other + 3 others) — optional reason note. NEW `enroll-editor` covers 4 enroll/remove workflow+sequence types — single `target_id` UUID input. NEW 8 flow-control editors: `wait-editor` (amount + unit picker minutes/hours/days, `delay_seconds` computed), `branch-editor` (yes-branch conditions via conditions-builder, no-edge implicit), `switch-editor` (path + dynamic cases list with add/remove), `ab-split-editor` (range slider 0–100 → `weights: [A, 100-A]`), `wait-for-event-editor` (filtered to `WAITABLE_EVENT_TYPES`, max-wait amount/unit, `contact_match` toggle, computes `max_wait_seconds`), `goal-editor` (name + outcome_label, defaults to `goal_reached`), `webhook-editor` (HTTPS-only URL with `/^https:\/\//i` regex validation, method/body-template/headers/expected status codes CSV/`on_failure` skip|error), `notify-user-editor` (recipient picker + title/body templates). `workflow-canvas.page.{ts,html}` updated: imports `NodeEditorComponent`, replaces the Step-14 JSON-stub right drawer with `<app-node-editor [node]="selectedNode()" (close)="state.selectNode(null)">` when a node is selected; test-fire trace + empty-state branches preserved when no node is selected. 26 sub-editor pairs + 2 shared helpers (`editor-contract.ts`, `send-editor-shared.ts`) + 1 dispatcher pair + 2 shared component pairs (`conditions-builder`, `variable-picker`) = 60 new files total. Jest specs deferred — frontend test infra is wired up by a separate step.
**Depends on:** Step 14 (canvas + node click handler + drawer scaffold). Step 6 (conditions AST). Step 7-11 (action handlers — the drawer config shape mirrors the handler's expected config).

---

## Scope

In-scope:

- `app/src/app/features/user/core/workflows/canvas/node-editor.component.{ts,html}`:
  - Right-side drawer body. Header: node name input + "Move to category" + "Disconnect" + "Delete".
  - Body switches on `node.type` via a typed form factory — one tiny component per node type, registered by string lookup. Pattern mirrors templates editor's per-channel sub-form approach.

- 42 node-config sub-components organised by category:

  **Triggers** (1):
  - `editors/trigger-editor.component` — event_type picker (Lucide-icon list from `EVENT_DESCRIPTIONS`), re-enrollment rule dropdown (once / daily / never), conditions AST builder (uses the shared `<app-conditions-builder>` from Step 6 frontend port — a tree of leaf nodes with op + path + value).

  **Sends** (7):
  - `editors/send-email-editor.component` — template picker (filtered to email templates published + read from central API per Step 15 of template-library), recipient resolver (radio: contact.email / user.email / lead.owner / custom-JSONPath), category (marketing / transactional / service), tracking flags. Reuses `<app-template-picker>` introduced in `tasks/template-library/step-15-campaigns-picker-unification.md`.
  - `editors/send-whatsapp-editor` — template picker (whatsapp + approved-by-Meta only), recipient (contact.phone), category.
  - `editors/send-sms-editor` / `send-fb-editor` / `send-ig-editor` / `send-push-editor` / `send-slack-editor` — similar shapes per channel.

  **Records** (8):
  - `editors/update-field-editor.component` — entity picker (contact / lead), field picker (system fields + custom fields), value source (literal | from-trigger-payload-JSONPath | from-context-variable), value editor (type-appropriate input).
  - `editors/create-task-editor`, `create-note-editor`, etc.

  **Routing** (5):
  - `editors/routing-editor.component` — mode (round_robin / least_loaded / territory / skill / specific_user), pool spec (role / team / explicit users via chip multiselect), target (lead.owner / contact.owner), fallback_resolver picker.

  **Tagging + lifecycle** (13):
  - `editors/tag-editor`, `list-editor`, `score-editor`, `convert-editor`, `unsubscribe-editor`, `block-editor`, `archive-editor`, `enroll-workflow-editor`, `enroll-sequence-editor`, etc.

  **Flow control** (8):
  - `editors/wait-editor.component` — duration_seconds + unit picker (min / hour / day) + max cap helper text.
  - `editors/branch-editor.component` — for-each-branch list of `{label, conditions}` entries; one always-`else` row pinned at the bottom.
  - `editors/switch-editor` — path picker + value cases.
  - `editors/ab-split-editor` — weight slider (50/50 default; weighted 60/40 option).
  - `editors/wait-for-event-editor` — event_type picker (filtered to events that can be "expected by a contact" like `email.opened`, `quote.viewed`, `whatsapp.message_received`), max_wait (duration + unit), contact_match toggle.
  - `editors/goal-editor` — name input + outcome label.
  - `editors/webhook-editor` — URL, method, body template, headers, expected status codes.
  - `editors/notify-user-editor` — recipient picker, title + body templates.

- Shared conditions-builder component `<app-conditions-builder>` — tree UI matching the conditions AST from Step 6. Supports AND / OR / NOT grouping + leaf comparison editor.

- Variable picker side panel — when any "template" or "rendered string" field is focused, a context-aware variable picker slides in showing the available paths for the current run context (mirrors templates editor's variable picker; per-event_type the available paths differ — e.g. `lead.created` exposes `{{lead.*}}`, `quote.sent` exposes `{{quote.*}}`).

- Validation surfacing — every node-editor sub-component implements `validate(): { valid: boolean, errors: string[] }`. The canvas node component listens via the canvas-state service; the red dot appears when any node returns invalid. Save / Activate buttons are gated on all-nodes-valid.

Out of scope:

- Mobile-responsive drawer (desktop only).
- "Test this single node" — covered by Step 14's whole-workflow test-fire.
- AI-assist for variable picking (deferred).

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/workflows/canvas/node-editor.component.{ts,html}` | **NEW** — drawer body + per-node-type switch |
| `APP/src/app/features/user/core/workflows/canvas/editors/trigger-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/send-email-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/send-whatsapp-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/send-sms-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/send-fb-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/send-ig-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/send-push-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/send-slack-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/update-field-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/create-task-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/create-note-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/create-appointment-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/create-quote-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/create-invoice-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/routing-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/tagging-editor.component.{ts,html}` | **NEW** — covers add/remove tag, add/remove list, set score |
| `APP/src/app/features/user/core/workflows/canvas/editors/lifecycle-editor.component.{ts,html}` | **NEW** — covers convert, unsubscribe, block, archive |
| `APP/src/app/features/user/core/workflows/canvas/editors/enroll-editor.component.{ts,html}` | **NEW** — covers enroll/remove workflow + sequence |
| `APP/src/app/features/user/core/workflows/canvas/editors/wait-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/branch-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/switch-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/ab-split-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/wait-for-event-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/goal-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/webhook-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/editors/notify-user-editor.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/canvas/conditions-builder.component.{ts,html}` | **NEW** — shared AST tree builder |
| `APP/src/app/features/user/core/workflows/canvas/variable-picker.component.{ts,html}` | **NEW** — context-aware variable picker |

**~30 files. ~1800 lines.** Largest step in the track — 27 typed editors land together. Each editor file is small (~50-80 lines); the volume comes from breadth.

## Plan

Group editors by category. Each category gets a couple of generic forms (e.g. tagging-editor handles 5 tag/list/score actions via a sub-mode switch).

1. Conditions-builder + variable-picker shared components.
2. Trigger editor (most-used).
3. Send editors (7 — start with email + WA; the others follow the same pattern).
4. Record editors (8 — update-field, create-task, etc.).
5. Routing + tagging + lifecycle editors.
6. Flow-control editors (wait, branch, switch, ab_split, wait_for_event, goal, webhook, notify_user).
7. node-editor.component switch dispatch.

## DB changes / migrations

None.

## Tests

8 Jest cases (spec'd in the most complex editors):

- trigger-editor: changing event_type refreshes the conditions-builder's available paths.
- send-email-editor: template picker filtered to email channel + published status.
- send-whatsapp-editor: only Meta-approved templates appear.
- update-field-editor: field picker shows system + custom fields.
- branch-editor: at least one branch always present + the else fallback can't be deleted.
- conditions-builder: AND/OR/NOT nesting renders + validates correctly.
- variable-picker: context-aware (lead.created → lead.* paths; quote.sent → quote.*).
- node-editor: clicking different node types swaps the sub-editor.

## Smoke

```
1. Open a workflow with a trigger node + send.email node.
2. Click trigger → drawer shows event_type=lead.created + condition tree builder.
3. Add a leaf: lead.score > 50. Save. Trigger node validation marker clears.
4. Click send.email → drawer shows template picker. Pick "Welcome". Set recipient=contact.email.
5. Validation marker on send.email clears.
6. Save Draft → workflow persists.
7. Add a branch node between trigger and send. Configure: branches = [{label: 'hot', conditions: {gt path=lead.score value=80}}, else].
8. Branch node validation marker clears once at least one labeled branch + the else are configured.
9. Activate workflow → all nodes validated → status=active.
```

## Risks

- 30 files in one step is at Rule 8's upper limit. Mitigation: every individual file is small + every editor follows the same shape so review is largely pattern-matching.
- Conditions-builder is the most complex sub-component — split into its own sub-step if the size balloons during implementation.
- Variable-picker context-awareness needs the backend to expose per-event-type variable schemas (the templates module's `variables_for_channel` is per-channel; per-event_type is a new dimension). Mitigation: extend Module B's `event_catalog.py` from Step 5 with a `VARIABLES_BY_EVENT` map — that's a small backend addition.

## Self-check (10 rules)

`core/workflows/` frontend only. ✓ org_id transparent. ✓ Custom fields rendered in update-field-editor. ✓ Static per-node-type forms — channel sub-forms, not custom-field-driven. ✓ N/A sidebar. Permissions enforced upstream. pack.yaml untouched. ✓ 30 files / ~1800 lines — at limit; could split into 15a (triggers + sends) + 15b (rest) if review needs it. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 15 — Node editor drawers
Files: 30
Verify: each of 42 node types renders a typed editor; validation marker clears when required fields complete; variable-picker context-aware per trigger event.
Tests: 8 Jest cases.
Awaiting "proceed".
```
