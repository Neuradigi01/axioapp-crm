# Step 2 — Service + DAL + graph validator + save-target registry

**Goal:** Land the layered service/DAL for bot CRUD, graph validation (DAG + connect-flow depth), and the registry-driven `bot_writable` allow-list picker used by Ask-* nodes.
**Depends on:** Step 1
**Status:** Pending

## Scope

**In-scope**
- `core/chatbots/service.py` — CRUD, publish/pause/archive, graph validation orchestration, version history writes, optimistic locking.
- `core/chatbots/data_access.py` — pure CRUD per single-file DAL convention.
- `core/chatbots/schemas.py` — Pydantic Create/Update/Read + GraphRead + node-schema unions.
- `core/chatbots/graph.py` — DAG validator, node-type parity check, cycle rejection, `connect_flow` chain-depth guard.
- `core/chatbots/save_target_registry.py` — reads standard-fields registry filtered by `bot_writable=true`; returns picker items grouped by entity.
- Extend `core/standard_fields/` registry with `bot_writable: bool` metadata column; seed the flag on existing definitions (safe defaults documented).
- Version history writes: every save appends prior graph to `tbl_chatbot_versions`.

**Out of scope**
- HTTP endpoints — Step 3.
- Trigger dispatch, engine, node handlers — Steps 5+.
- Frontend picker consuming the endpoint — Step 14.

## Files to touch

- `API/src/app/core/chatbots/schemas.py` (created)
- `API/src/app/core/chatbots/data_access.py` (created)
- `API/src/app/core/chatbots/service.py` (created)
- `API/src/app/core/chatbots/graph.py` (created)
- `API/src/app/core/chatbots/save_target_registry.py` (created)
- `API/src/app/core/standard_fields/models.py` (modified — add `bot_writable` column)
- `API/src/app/core/standard_fields/data_access.py` (modified — expose filter)
- `API/alembic/versions/0187_bot_writable_flag.py` (created)

## Plan

1. Alembic 0187 — add `bot_writable BOOLEAN DEFAULT FALSE NOT NULL` on `tbl_standard_field_definitions`; data-migration flips the flag to `true` on safe fields (Contact: first_name, last_name, email, phone, birthday, address_line_1, city, state, postal_code; Lead: title, notes; Deal: notes). Sensitive fields (`role`, `owner_id`, `org_id`, `is_active`, `balance`, tier, verification timestamps, `pin_hash`) stay `false`.
2. `schemas.py` — Pydantic v2 models: `ChatbotCreate`, `ChatbotRead`, `ChatbotUpdate` (accepts `expected_version` for optimistic locking), `GraphRead` (nodes + edges), per-node-type config schemas (23 discriminated union).
3. `graph.py` — `validate_graph(graph)` runs: (a) DAG check via topo sort (cycle → reject); (b) every node type resolves in `node_type_registry`; (c) every edge references existing nodes; (d) `connect_flow` chain depth ≤ 5 via recursive check across bots in same org; (e) trigger card is present exactly once and unconnected on the input side.
4. `save_target_registry.py` — `list_save_targets(entity, org_id)` returns `[{entity, field_key, display_label, format, is_custom}]`; standard fields where `bot_writable=true` + all custom fields for that org+entity. Custom field key regex `^[a-z0-9_]{1,40}$` enforced here; collision with system column names returns 422.
5. `data_access.py` — `insert_chatbot`, `get_chatbot`, `list_chatbots`, `update_chatbot`, `soft_delete_chatbot`, `insert_chatbot_version`, `list_versions`, plus meter reads. Pure CRUD, no transactions.
6. `service.py` — orchestration methods; the ONLY layer that calls `db.commit/rollback/flush/refresh` per layered-architecture rule; `save_chatbot()` validates graph, writes version-history row, increments `version_number`, then commits.

## DB changes / migrations

Revision `0187_bot_writable_flag` (24 chars). Data migration in same file sets the flag on the ~15 seed fields listed above.

## Tests to add

Location: `API/tests/core/chatbots/`

- `test_service_optimistic_locking` — stale `expected_version` → 409.
- `test_graph_validator_rejects_cycles`
- `test_graph_validator_rejects_missing_node_type`
- `test_graph_validator_rejects_connect_flow_chain_over_5`
- `test_save_target_registry_excludes_role_owner_balance` — T24 assertion.
- `test_save_target_registry_includes_first_name`
- `test_save_target_custom_field_key_regex_enforced`
- `test_save_target_custom_field_collision_with_system_column_rejected`
- `test_version_history_appended_on_save`

## Verification checklist

**Backend**
- [ ] `run.cmd upgrade` applies 0187; `bot_writable` visible in `\d tbl_standard_field_definitions`.
- [ ] `pytest tests/core/chatbots/` all passes.
- [ ] `service.py` transaction-boundary pin-test still green (only service calls commit).

**Frontend** — N/A.

**Code review**
- [ ] DAL has zero `db.commit/rollback/flush/refresh`.
- [ ] Service is the only file with transaction control.
- [ ] `schemas.py` uses Pydantic v2 syntax (`ConfigDict`, `model_config`, `Field`).
- [ ] Graph validator handles empty graph, single trigger, and disconnected islands gracefully.

## Self-check (10 rules)

- [ ] `core` did not import `packs`
- [ ] `org_id` filters on every query in DAL
- [ ] Custom-fields registry (rule #3) extended, not bypassed
- [ ] Sidebar registry not touched (Step 3)
- [ ] Permissions not touched (Step 3)
- [ ] Under 10 files, under 400 lines total
- [ ] Query efficiency — no N+1 in `list_chatbots` (fetch versions + meters via `selectinload`)
- [ ] Zero TODOs

## Stop & report

Report DAL function list, service method list, and the raw INSERT SQL for the `bot_writable=true` seed flags. Await "proceed".
