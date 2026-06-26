# Step 6 — Condition AST + branch evaluator

**Goal:** A typed predicate AST + an evaluator that runs against the engine's `context` dict. Used by trigger-node conditions (filter incoming events), branch nodes (if/else), and switch nodes (multi-way). Same evaluator powers Module B's trigger conditions when that step ships, so the AST lives in a shared `core/events/` helper.
**Status:** Pending
**Depends on:** Step 5 (subscribers exist; conditions previously short-circuited to "always true").

---

## Scope

In-scope:

- `core/events/conditions.py` — pure helper (no DB, no I/O):
  - JSON-shaped AST nodes:
    - `{op: 'eq' | 'neq' | 'gt' | 'gte' | 'lt' | 'lte' | 'in' | 'not_in' | 'contains' | 'starts_with' | 'ends_with' | 'matches' | 'exists' | 'is_null', path: 'contact.first_name', value: 'Asha' }` — leaf comparisons. `path` is a dot-path against the context; `matches` is regex.
    - `{all: [<node>, ...]}` — AND.
    - `{any: [<node>, ...]}` — OR.
    - `{not: <node>}` — negation.
  - `evaluate(node: dict, context: dict) -> bool` — recursive walker. Empty `{}` returns True (the "always match" default). Unknown ops raise `InvalidCondition`.
  - `extract_paths(node: dict) -> set[str]` — utility for the diagnostics step (Step 19) so the "why didn't this fire?" tool can show which context paths the condition cares about.
  - `validate(node: dict) -> None` — schema-shape check (op + path present for leaves; AND/OR have non-empty children). Used by Step 2's graph validator + Step 15's node-editor save handler.

- `core/workflows/engine.py` patched:
  - Trigger-node enrollment check now calls `evaluate(trigger_node['config']['conditions'], context)` instead of returning True unconditionally.
  - Branch-node handler resolves `next_edge_label` by walking the node's `branches: [{label, conditions}]` array (config shape) and returning the first matching label. If none match, returns the fallback label `else` (every branch node MUST have an `else` edge — Step 2's validator enforces).
  - Switch-node handler is similar but `branches` exhaustively enumerate possible values for a single path; matches by equality, falls through to `default`.

- `core/workflows/actions/flow_control.py` stub gets two handlers wired (`branch` + `switch`); the rest (`wait`, `ab_split`, `goal`, `wait_for_event`) land in Step 11. `branch` + `switch` come first because they're the bare minimum for the condition AST tests to be end-to-end runnable.

- The trigger handler's enrollment-decision tree:
  1. Workflow active + `event_type` matches. → proceed
  2. `evaluate(trigger.conditions, context)` → if False, log "trigger condition rejected" + audit row in `tbl_workflow_step_runs` with `skip_reason='condition_failed'` so the diagnostics tool can show it. No run row created.
  3. Re-enrollment check (Step 5 logic).
  4. `start_run`.

  This means the trigger node's `skipped` decision DOES leave a breadcrumb — operators can answer "why didn't my workflow fire for contact X" later. The audit row is org-scoped + carries the workflow_id even though no run exists.

Out of scope:

- `lead.score_threshold` complex predicate (e.g. "score crossed 75 going up vs going down") — that's the trigger-emit publisher's job, not the condition AST. The publisher fires the event when the threshold was crossed; the workflow's condition AST just filters on incoming payload.
- Custom JS / user-supplied code paths — strict JSON AST only. Rejects any unexpected keys.
- Time-window conditions ("only on weekdays") — Step 12's compliance gates handle quiet hours; weekdays-only is a follow-up.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/events/conditions.py` | **NEW** |
| `API/src/app/core/workflows/engine.py` | edit — call `evaluate` for trigger-node check |
| `API/src/app/core/workflows/actions/flow_control.py` | **NEW** — `branch` + `switch` handlers |
| `API/src/app/core/workflows/trigger_handlers.py` | edit — log skip when condition False |
| `API/src/app/core/workflows/graph.py` | edit — validator calls `conditions.validate(...)` per node |
| `API/tests/workflows/test_conditions.py` | **NEW** |
| `API/tests/workflows/test_branch_handler.py` | **NEW** |

**~7 files. ~400 lines.**

## Plan

1. Conditions AST + evaluator + validator — pure helper file, easy to unit-test.
2. Branch / switch handler stubs in `actions/flow_control.py` registered for `flow_control.branch` + `flow_control.switch`.
3. Engine + trigger-handler edits to call the evaluator.
4. Graph-validator edits to validate condition shape per node.
5. Tests: 14 evaluator cases (one per op + nesting) + 6 handler cases.

## DB changes / migrations

None.

## Tests

20 pytest cases:

- Evaluator: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `contains`, `starts_with`, `ends_with`, `matches`, `exists`, `is_null` — 14 leaf checks.
- `all: [...]` AND short-circuits on first false.
- `any: [...]` OR short-circuits on first true.
- `not: ...` negates.
- Empty `{}` returns True.
- Unknown op raises `InvalidCondition`.
- Branch handler: first matching label returned; else fallback when none match; rejects missing else edge at validation time.

## Smoke

```
1. Create a workflow: trigger(event_type='lead.created', conditions={op:'gt', path:'lead.score', value:50})
   → send action.
2. publish lead.created with {lead: {score: 30}, contact: {...}} → no run started; skip_reason='condition_failed' in step_runs.
3. publish lead.created with {lead: {score: 75}, contact: {...}} → run started → send action fires.
4. Add a branch node after trigger: branches=[{label:'high', conditions:{op:'gt',path:'lead.score',value:80}}, {label:'else', conditions:{}}].
5. publish lead.created with {lead: {score: 90}} → run takes 'high' edge.
6. publish lead.created with {lead: {score: 60}} → run takes 'else' edge.
```

## Risks

- Regex (`matches` op) — accept user-supplied patterns, but reject any pattern that compiles to a state machine over 1000 chars. Mitigation: `re.compile(pattern, flags=re.IGNORECASE)[:1000]` length check at validate-time.
- Dot-path resolution against `None` intermediate values — return False for any leaf comparison on missing data; don't raise.
- Future scope creep (adding `between`, `in_last_n_days`, etc.) — only add ops when an actual seeded workflow needs them. Resist op-bloat.

## Self-check (10 rules)

`core/events/` + `core/workflows/`. ✓ No DB. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions reused. pack.yaml untouched. ✓ 7 files / ~400 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 6 — Condition AST + branch evaluator
Files: 7
Verify: 14 leaf ops + AND/OR/NOT nesting work; trigger conditions filter enrollments; branch + switch nodes pick edges by predicate.
Tests: 20 pytest cases.
Awaiting "proceed".
```
