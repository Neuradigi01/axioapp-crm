# Workflows — multi-step visual flowchart engine (Module C)

The third and final module in the three-track plan locked by the manager on 2026-06-25:

1. **Templates** — `core/templates/` — central library for every channel. ✅ Shipped (15 steps, `tasks/template-library/`).
2. **Automation** — `core/automation/` — single-event, one-action triggers. 📋 Specced (14 steps, `tasks/automation-engine/`).
3. **Workflows** — `core/workflows/` — multi-step visual flowcharts with branches, delays, A/B tests, and analytics. 📋 **This track.**

Workflows is the HubSpot Workflows / Zoho Marketing Automation Journeys / Salesforce Process Builder + Journey Builder equivalent. Beyond single-event triggers (Module B), operators get a drag-and-drop canvas where one event fires a chain of actions — wait 24h, branch on lead score, send template A or B, wait for the contact to click, goal node for ROI math — and the engine threads contacts through it.

## Why workflows aren't just "automation but bigger"

| | Module B — Automation | Module C — Workflows |
|---|---|---|
| Shape | 1 event → 1 action | 1 event → chain of actions |
| Branching | None | If/else, switch, A/B split, goal nodes, wait-for-event |
| Delays | One fixed delay (e.g. "send after 24h") | Per-step delays, wait-for-event with max-wait timeout |
| UI | Simple form ("when X happens, send template Y") | Drag-and-drop canvas with node palette |
| Config time | ~30 seconds | Minutes to design a real journey |
| Use case | 80% of "send X when Y happens" | Complex nurtures, lifecycle journeys, lead routing |
| Persistence | One row per fire (`tbl_automation_runs`) | Run + per-step-run rows (`tbl_workflow_runs` + `tbl_workflow_step_runs`) so the run-history shows exactly where each enrollment is in the flow |

Both modules consume the same event bus and event catalog from Module B (`core/events/`). Module C reuses Module B's variable engine, channel adapters, and recipient resolvers — no duplication. The schema and execution engine are new because workflow runs are stateful (an enrollment can sit at a wait node for 7 days before resuming) and the UI is fundamentally different (canvas vs form).

## Locked design choices (won't relitigate during implementation)

These are baked in from the manager spec + standard industry patterns. Steps reference them but don't re-derive.

### 1. Workflows are DAGs of typed nodes

A workflow is a Directed Acyclic Graph of nodes connected by edges. Each node has a `type` (trigger / send / record-update / routing / tag / lifecycle / wait / branch / switch / ab_split / goal / wait_for_event / sub_workflow / webhook / internal). Each edge has an optional `label` (used by branch/switch/ab_split nodes to identify which outbound edge to take). Cycles are rejected at validation time. The graph is stored as JSONB on `tbl_workflows.graph` — separate node + edge tables would force three-table joins on every read and the JSONB shape works for builders that swap entire layouts at once.

### 2. Per-step run rows give exact resume + diagnostics

`tbl_workflow_runs` tracks the enrollment lifecycle (started / running / completed / paused / canceled / errored). `tbl_workflow_step_runs` is one row per step a given run hit — current step's row is in `pending` / `running`; previous steps are `completed` / `skipped` / `errored`. Resuming after a wait re-reads the current step row and walks forward. The "why didn't this fire?" diagnostics (Step 19) walks step_runs to show the operator exactly which condition rejected the contact.

### 3. Triggers come from Module B's event bus

`core/workflows/` subscribes to the same event types Module B publishes (`lead.created`, `appointment.booked`, `quote.sent`, …). No re-emit; no duplicate event catalog. Step 6 documents the subscription handler shape. If Module B's `core/events/event_catalog.py` doesn't exist yet (Step 6 of `tasks/automation-engine/` hasn't shipped when workflows starts), Step 5 of this track creates it as a side-effect import file — both modules then share it.

### 4. Re-enrollment rules are per-workflow, not global

Three modes: `once` (default — one enrollment per contact per workflow, ever), `daily` (max one per day), `never` (multiple concurrent allowed — needed for stale-7d/stale-30d/stale-90d chains). Step 5 implements; the workflow editor exposes it on the trigger node.

### 5. Compliance is enforced at Send actions, not at trigger time

A trigger can fire and walk through several steps before reaching a Send. The compliance gates (marketing consent, quiet hours, frequency cap) live inside the Send action's pre-flight check, NOT at the trigger. This matches HubSpot's model and lets transactional Send actions (invoice / quote / receipt) inside marketing workflows still go through — the per-action `category` flag overrides the workflow's marketing category.

### 6. A/B testing is **between two whole workflows**, not within one

A workflow can carry an optional sibling pointer (`tbl_workflows.ab_sibling_id`). When set, the trigger handler 50/50-splits new enrollments between the two. After a configurable hold-back window (default 7 days), the engine picks the winner by goal-conversion metric and auto-promotes (loser archived, winner becomes the default for new enrollments). Within-workflow A/B-split nodes also exist (Step 11) for finer-grained tests, but full-workflow A/B is the marquee feature operators expect.

### 7. The visual builder is canvas-based, not form-list-based

Step 14 ships an Angular canvas (Konva.js or custom SVG — TBD in the step) with a node palette on the left, the canvas in the middle, and a node-config drawer on the right. Drag from palette → drop on canvas → connect edges by dragging from output port to input port → click node to edit config. Auto-layout helper for "tidy up" but operators can position freely.

### 8. Email sequences become the "linear sequence" workflow type

`core/email_sequences/` (today: Settings → Email Sequences tab) is absorbed in Step 20. The existing sequence-builder UI is reused — wrapped as a workflow node graph with no branches, just a linear `trigger → wait → send → wait → send → …` chain. Settings tab is removed; the existing routes redirect to the new Workflows sidebar entry.

## Module-level architecture

```
core/workflows/
├── __init__.py
├── models.py             ← tbl_workflows + tbl_workflow_runs + tbl_workflow_step_runs + enums
├── schemas.py            ← Pydantic Create/Update/Read + GraphRead + RunRead + StepRunRead
├── router.py             ← REST endpoints
├── service.py            ← CRUD + graph validation + enrollment + workflow lifecycle
├── engine.py             ← Step processor: walk graph, schedule next step, handle waits
├── data_access.py        ← Single-file DAL per locked convention
├── module.py             ← Sidebar + permission registration
├── tasks.py              ← Celery tasks: step processor + A/B winner-selection sweep
├── actions/              ← Pluggable action handlers (one file per action category)
│   ├── __init__.py       ← register_action(action_type, handler) registry
│   ├── send.py           ← Send actions (email / WA / SMS / FB / IG / push / Slack)
│   ├── records.py        ← Update field / create task / note / appointment / quote / invoice
│   ├── routing.py        ← Round-robin / least-loaded / territory / skill
│   ├── tagging.py        ← Add/remove tag, set score, add to list
│   ├── lifecycle.py      ← Status change, mark converted, opt-out
│   └── flow_control.py   ← Wait, if/else, switch, A/B split, goal, wait-for-event
├── trigger_handlers.py   ← Event-bus subscribers (one per supported event_type)
├── conditions.py         ← Condition AST + evaluator (reused from automation-engine pattern)
├── compliance.py         ← Marketing consent, quiet hours, frequency cap gates
├── diagnostics.py        ← "Why didn't this fire?" trace engine
└── seeds.py              ← Default 15 core seeded workflows
```

The `actions/` sub-package is the only one allowed beyond the single-file convention — it's a registry of plug-in handlers, same shape as `core/conversations/adapters/`. Each `actions/*.py` self-registers on import via `core/workflows/actions/__init__.py`'s side-effect imports.

## Steps index

| # | Title | Status | Effort |
|---|---|---|---|
| 1 | [Workflow schema + models + node graph tables](step-1-schema-and-models.md) | **COMPLETED** | ~1 day |
| 2 | [Workflow service + graph validator](step-2-service-and-graph-validator.md) | **COMPLETED** | ~1 day |
| 3 | [Workflow router + permissions registry](step-3-router-and-permissions.md) | **COMPLETED** | ~0.5 days |
| 4 | [Execution engine + Celery step processor](step-4-execution-engine.md) | **COMPLETED** | ~1.5 days |
| 5 | [Trigger subscriptions + re-enrollment rules](step-5-trigger-subscriptions.md) | **COMPLETED** | ~1 day |
| 6 | [Condition AST + branch evaluator](step-6-conditions-and-branches.md) | **COMPLETED** | ~0.5 days |
| 7 | [Send actions (email / WA / SMS / FB / IG / push / Slack)](step-7-send-actions.md) | **COMPLETED** | ~1 day |
| 8 | [Record actions (update fields, create task/note/quote/invoice)](step-8-record-actions.md) | **COMPLETED** | ~1 day |
| 9 | [Routing actions (round-robin / least-loaded / territory)](step-9-routing-actions.md) | **COMPLETED** | ~1 day |
| 10 | [Tagging + lifecycle actions](step-10-tagging-lifecycle-actions.md) | **COMPLETED** | ~0.5 days |
| 11 | [Flow control (wait / if-else / switch / A/B / goal / wait-for-event)](step-11-flow-control-actions.md) | **COMPLETED** | ~1 day |
| 12 | [Marketing consent + quiet hours + frequency cap compliance](step-12-compliance-gates.md) | **COMPLETED** | ~1 day |
| 13 | [Workflow list UI + folders/categories](step-13-workflow-list-ui.md) | **COMPLETED** | ~1 day |
| 14 | [Workflow canvas UI (node palette + drag-drop)](step-14-workflow-canvas-ui.md) | **COMPLETED** | ~2 days |
| 15 | [Node editor drawers (per-node config)](step-15-node-editor-drawers.md) | **COMPLETED** | ~1.5 days |
| 16 | [Templates gallery + clone-from-default](step-16-templates-gallery.md) | **COMPLETED** | ~0.5 days |
| 17 | [Version history + rollback + import/export JSON](step-17-version-history.md) | **COMPLETED** | ~1 day |
| 18 | [A/B test entire workflows + winner selection](step-18-ab-testing.md) | **COMPLETED** | ~1 day |
| 19 | [Analytics + "why didn't this fire?" diagnostics](step-19-analytics-and-diagnostics.md) | **COMPLETED** | ~1.5 days |
| 20 | [Default workflow seeder + email_sequences absorption](step-20-seeded-workflows-and-sequences-absorption.md) | **COMPLETED** | ~1.5 days |

**Total: 20 steps, ~21 days.**

After this track closes, **all three modules of the three-track plan are shipped**. The CRM has a complete templates → automation → workflows pipeline matching the manager's HubSpot/Zoho/Salesforce reference pattern.

## UI surfaces touched

| Page | What changes | In which step |
|---|---|---|
| Sidebar | NEW top-level "Workflows" entry. Settings → Email Sequences entry removed (absorbed). | Step 3 + Step 20 |
| Workflows list (NEW) | Filter (channel / category / status), folders/categories, "Create from template" CTA, status badges, analytics summary per row | Step 13 |
| Workflow canvas (NEW) | Node palette + drag-drop graph editor + edge connection + node-config drawer + "Save / Activate / Test fire" header buttons | Step 14 + Step 15 |
| Workflow templates gallery (NEW) | Read-only catalog of the 15 default seeded workflows; "Use this" clones into the operator's library | Step 16 |
| Workflow run history (NEW) | Per-enrollment timeline showing each step's status, with "why" trace for skipped/errored rows | Step 19 |
| Workflow analytics dashboard (NEW) | Enrolled / completed / exited-at-step funnel, goal-conversion rate, send-metric rollup, cost estimate | Step 19 |
| Workflow A/B comparison (NEW) | Side-by-side stats for two-workflow A/B winners | Step 18 |
| Workflow diagnostics (NEW) | "Pick a contact + event" → trace each enabled workflow's eligibility check + condition eval | Step 19 |
| Settings → General | Quiet-hours window + frequency-cap controls (org-level) + marketing-consent policy | Step 12 |
| Settings → Email Sequences | **REMOVED** — replaced by workflow type "linear sequence" | Step 20 |

## Layered backend convention (LOCKED)

Every module under `core/workflows/` follows the standard 5-file domain-driven layout (manager spec 2026-06-25, single-file `data_access.py` per memory `feedback_backend_layered_architecture.md`):

- `models.py` — SQLAlchemy ORM only.
- `schemas.py` — Pydantic.
- `router.py` — HTTP only; no SQL, no DB calls beyond `Depends(get_db)` for handler signature.
- `service.py` — Business logic + the ONLY layer that touches transactions.
- `data_access.py` — Pure CRUD; never commits.

Exceptions to the single-file rule (allowed for this module):

- `engine.py` — execution-loop logic that doesn't fit Router→Service→DAL (it's a stateful step processor invoked by Celery, not a request handler). Treated as part of `service.py` for the layered-architecture pin-test (it commits state transitions).
- `actions/` — pluggable handler registry (mirrors `core/conversations/adapters/`).
- `tasks.py` — Celery task entrypoints (one-line wrappers around `engine.process_step(...)`).
- `trigger_handlers.py` — event-bus subscribers (one-line wrappers around `service.enroll_contact(...)`).
- `conditions.py` — pure helper (no DB).
- `compliance.py` — pure helper (no DB except a read of `tbl_org_settings`).
- `diagnostics.py` — read-only debugging surface (no writes).
- `seeds.py` — one-shot installer for default workflows; invoked from `tenant_provisioning`.

These all live alongside `service.py` and `data_access.py`. New helper files inherit the existing exception list — no new entries unless absolutely necessary.

## The 10 rules — track-wide notes

- **Rule 1** (core never imports packs): Workflows module is pure `core/`. Default seeded workflows are CORE patterns only (lead lifecycle, sales, customer onboarding, engagement, internal). Vertical-specific workflows (Furniture: Showroom Visit Thank You, Custom Order Confirmation, Warranty Reminder, Festival Sale) live in `packs/furniture/pack.yaml` when the pack's workflows track lands — not here. ✓
- **Rule 2** (org_id + RLS): Every new table — `tbl_workflows`, `tbl_workflow_runs`, `tbl_workflow_step_runs`, `tbl_workflow_versions`, `tbl_workflow_folders` — has `org_id` FK + RLS policy from its first migration. ✓
- **Rule 3** (custom fields): N/A — workflow definitions don't expose custom fields to end users.
- **Rule 4** (dynamic forms): N/A — the node editor drawers are static per node type. The form fields the operator fills inside a node config come from the node-type schema, not from `custom_field_definitions`.
- **Rule 5** (sidebar registry): NEW sidebar entry registered via `core/workflows/module.py` in Step 3. Core doesn't hardcode it.
- **Rule 6** (permission registry): NEW permission keys (`workflows.read / write / activate / clone / view_analytics / view_diagnostics`) registered in Step 3.
- **Rule 7** (pack.yaml): no furniture defaults change. The pack's workflows track adds vertical-specific seeded workflows via `pack.yaml`; this track only ships the core ones.
- **Rule 8** (step size): every step ≤ ~10 files / ~400 lines, individually shippable. Visual builder steps (14 + 15) are larger but split — canvas in 14, drawer in 15. Analytics step (19) splits into list-page summary + detail page + diagnostics view.
- **Rule 9** (no skipping verification): stop-report after each step.
- **Rule 10** (no TODOs): every step leaves the codebase clean and runnable.

## What's NOT in v1 (deferred to a Workflows v2 track if needed)

Per manager memory `project_central_template_library.md`:

- **Send-time optimization** (best-time-to-send AI per recipient).
- **Best-channel selection** (try WhatsApp, fall back to email if no read).
- **Predictive lead scoring** that drives branches.
- **AI-suggested workflows** from event-history data.
- **Multi-org workflow marketplace** (operator imports a workflow another org published).
- **External event sources** (Zapier ingestion, custom webhooks-in).
- **Visual funnel analytics inside the canvas** (heatmap of where contacts exit).

None of these block v1. Workflows v1 is the foundation operators need to ship complex journeys today; v2 layers AI + integrations on top of that foundation.
