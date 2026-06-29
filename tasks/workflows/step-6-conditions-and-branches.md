# Step 6 — Condition AST + branch evaluator

**Goal:** A typed predicate AST + an evaluator that runs against the engine's `context` dict. Used by trigger-node conditions (filter incoming events), branch nodes (if/else), and switch nodes (multi-way). Same evaluator powers Module B's trigger conditions when that step ships, so the AST lives in a shared `core/events/` helper.
**Status:** COMPLETED — NEW `core/events/conditions.py` ships the shared AST with 14 leaf ops (`eq`/`neq`/`gt`/`gte`/`lt`/`lte`/`in`/`not_in`/`contains`/`starts_with`/`ends_with`/`matches`/`exists`/`is_null`) + AND/OR/NOT compound nodes. Leaf shape: `{op, path, value}` (using `path` not `field` so it differs from Module B's existing `core/automation/conditions.py` — Module B will migrate onto this shared one in a future step). `evaluate(node, context) → bool` is the strict recursive walker (raises `InvalidCondition` on unknown ops); `evaluate_safe(node, context)` swallows the exception + logs at WARN so one bad workflow can't poison every event publish. `validate(node)` is the publish-time schema check (rejects unknown ops, missing required keys, empty compound lists, oversize regex >1000 chars, unknown leaf keys, compound nodes carrying leaf fields). `extract_paths(node)` returns the set of dot-paths the condition references — drives Step 19's "why didn't this fire?" diagnostics. `_resolve_path` walks dot-paths with missing-key tolerance (returns `_MISSING` sentinel; non-`exists`/`is_null` ops fail-False on missing). Regex op uses `re.search` with a 1000-char pattern cap (ReDoS defence); the validate-time check compiles the pattern + reports the error verbatim. NEW `core/workflows/actions/flow_control.py` ships two action handlers: `_branch_handler` walks `config.branches: [{label, conditions}]` and returns the first matching label via `evaluate_safe`, falling through to `"else"`; `_switch_handler` reads `config.path` once + matches by equality against `branches[].value`, falling through to `"default"`. Both registered into the action registry on module import so the engine resolves `branch.if` / `branch.switch` without a special case. `core/workflows/__init__.py` extended with the side-effect `from src.app.core.workflows.actions import flow_control` so the branch handlers register at package init alongside the trigger subscribers. `core/workflows/trigger_handlers.py` extended: BEFORE the re-enrollment check `_maybe_start_run`, `_on_event` now calls `_trigger_conditions_match(workflow, payload)` which reads the trigger node's `config.conditions` + runs `evaluate_safe`. A False verdict logs the rejection at INFO + skips enrolment without creating any DB rows — the spec-suggested step_runs breadcrumb would require making `tbl_workflow_step_runs.run_id` nullable (schema change deferred); v1 surface is the log line, Step 19 can lift it into a dedicated enrollment-decisions table when ready. `core/workflows/graph.py` validator extended: (1) every branch node now MUST have an outbound edge labelled `"else"` for `branch.if` or `"default"` for `branch.switch` so unmatched cases can't silently terminate the run; (2) new check #11 calls `conditions.validate` against trigger-node `config.conditions`, condition-node `config.conditions`, and every `branch.if` branch's `conditions` so the operator gets a 422 with the AST reason at publish time instead of a runtime miss. 23 pytest cases in `test_conditions.py`: 14 leaf ops + missing-data fail-closed × 2 + AND/OR short-circuit + NOT + empty-{} always-match + unknown-op raises + evaluate_safe swallows + extract_paths walks compound + 7 validate() cases (well-formed, unknown op, missing value, empty all, unknown leaf keys, oversize regex, compound-with-leaf-fields). 8 pytest cases in `test_branch_handler.py`: branch picks first match, falls through to else, empty config → else; switch matches by value, falls through to default, missing path → default; graph validator rejects branch missing else edge / switch missing default edge / branch with malformed condition AST. Pytest run deferred per `feedback_pause_before_pytest.md`. No migration needed — pure helper module + handler registrations.

**Spec deviation**: The spec said "audit row in `tbl_workflow_step_runs` with `skip_reason='condition_failed'` so the diagnostics tool can show it. No run row created." But Step-1's migration declared `tbl_workflow_step_runs.run_id` as NOT NULL with a FK to `tbl_workflow_runs(id)`, so writing an orphan step_run isn't possible without a schema change. For v1 the rejection is logged at INFO level. Step 19's diagnostics surface (or a future schema migration making run_id nullable + creating a dedicated `tbl_workflow_enrollment_decisions` table) will close the gap; the spec-MD wording will be reconciled with the implemented surface in that step.
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
