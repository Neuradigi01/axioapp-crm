# Step 6 — Assistant CRUD service + router (guards, OCC, mass-assignment-safe)

**Goal:** Ship the operator-facing REST for assistants — list, get, create, update, archive, delete. RBAC on `ai_assistants.view` / `.manage`. Cross-org `key_id` validation. Timing-safe 404 for wrong-org vs nonexistent. Optimistic concurrency via `version` column. Mass-assignment-safe write schemas. Instruction changes write audit log via the shared helper. No knowledge, no chat, no UI yet — those land in Steps 7–13.
**Status:** COMPLETED — 8 files landed (2 new + 5 edits + 3 tests). Full CRUD service in `core/ai_assistants/service.py` (list/get/create/update/archive/delete), 6-endpoint router at `/api/v1/ai-assistants`. Full Pydantic schemas with `extra='forbid'` on writes (rejects `org_id` / `id` / `version` / `created_by_user_id` / `status` / audit cols at 422 before the service sees them). Timing-safe 404 pattern: `get_assistant_row_no_org_filter` runs a bare-SQL lookup that hits DB whether the id is wrong-org or nonexistent; service compares `org_id` in Python and raises the SAME `HTTPException` with the SAME detail string (`"assistant not found"`) on both branches; test proves body-parity AND SQL-emission-shape parity via SQLAlchemy event listener. Cross-org `key_id` guard uses the TenantScoped auto-filter (None result → 404, never leaks existence — Attacker H3). OCC via SQLAlchemy's `version_id_col` machinery — auto-increments on every UPDATE, adds `AND version = :current` to the WHERE, raises `StaleDataError` on race → 409. Instruction audit rows written for every change to `instructions` / `model` / `temperature` / `allowed_domains` / `output_sanitizer_enabled` (Attacker H8 defence). Two bug-fixes surfaced during test-run: (1) `StaleDataError` moved from wrong import path `sqlalchemy.exc` to correct `sqlalchemy.orm.exc`; (2) Step 5's post-class `__mapper_args__ = {...}` reassignment was a no-op — SQLAlchemy builds the mapper at class-definition time. Moved `__mapper_args__` inside the class body referencing the `version` mapped_column directly, and removed the stray `version_id_generator: False` that had been suppressing auto-increment. 97 tests green in 22.83s (25 Step 1 + 21 Step 2 + 19 Step 4 + 16 Step 5 + 16 Step 6).
**Depends on:** Step 5 (tables + models + placeholder DAL).

---

## Scope

In-scope:

- Full Pydantic schemas in `core/ai_assistants/schemas.py`:
  - `AiAssistantCreate` — accepts `name`, `description`, `key_id`, `model`, `temperature`, `instructions` (optional at create), `stop_keywords`, `retry_attempts`, `fallback_message`, `allowed_domains`, `output_sanitizer_enabled`, `budget_cap_override_usd`. **Explicitly rejects** `org_id`, `id`, `version`, `created_by_user_id`, `interface_config`, `styling_config`, `status`, audit cols, `key_version` on the key. `Config.extra = 'forbid'`.
  - `AiAssistantUpdate` — same fields but all optional. Adds required `version` field for OCC.
  - `AiAssistantRead` — full assistant minus the audit table; includes computed `has_knowledge` bool.
  - `AiAssistantListItem` — trimmed for list view (name, status, model, knowledge_count, message_count_last_30d).
- Service in `core/ai_assistants/service.py`:
  - `list_assistants(db, org_id, filter_status)` — paginated.
  - `get_assistant(db, org_id, assistant_id)` — **timing-safe 404**: always execute `SELECT * FROM tbl_ai_assistants WHERE id = :id LIMIT 1`, then filter `org_id` in Python; if mismatch OR no row, raise 404 with identical body.
  - `create_assistant(db, org_id, user_id, payload)` — validates `key.org_id == org_id` (cross-org guard: get key by id without RLS filter first, then check); 404 if mismatch. Instruction audit row written on create if `instructions` set.
  - `update_assistant(db, org_id, user_id, assistant_id, payload)` — OCC: `UPDATE ... WHERE id = :id AND version = :version RETURNING id`; if no row returned, raise 409. If payload contains `key_id`, cross-org check. If `instructions` changes, write audit row with `old_value`/`new_value` in same transaction.
  - `archive_assistant(db, org_id, assistant_id)` — sets `status='archived'`, does not delete.
  - `delete_assistant(db, org_id, assistant_id)` — hard-delete (FK cascades knowledge + chunks + audit; message_meta.assistant_id SET NULL). Requires confirmation flag in payload.
- Router in `core/ai_assistants/router.py`:
  - Depends on `require_permission("ai_assistants.view")` for GETs, `require_permission("ai_assistants.manage")` for POST/PATCH/DELETE.
  - `GET /ai-assistants` — list.
  - `GET /ai-assistants/{id}` — read.
  - `POST /ai-assistants` — create.
  - `PATCH /ai-assistants/{id}` — update.
  - `POST /ai-assistants/{id}/archive` — archive.
  - `DELETE /ai-assistants/{id}` — hard-delete, requires `?confirm=true` query.
- Data access in `core/ai_assistants/data_access.py`:
  - `list_assistants(db, org_id, filter_status, limit, offset)`.
  - `get_assistant_by_id_no_org_filter(db, assistant_id)` — used for timing-safe 404 (returns row regardless of org; service checks).
  - `insert_assistant(db, values)`.
  - `update_assistant_optimistic(db, assistant_id, version, values)` — WHERE ... AND version = :version RETURNING.
  - `delete_assistant(db, org_id, assistant_id)`.
  - `insert_instruction_audit(db, values)`.
  - `get_provider_key_by_id_no_org_filter(db, key_id)` — cross-org guard input.
- Instruction-audit helper `_write_instruction_audit(db, org_id, assistant_id, user_id, field_name, old, new)` — service-internal.

Out of scope:
- Frontend (Step 7).
- Chat runtime, knowledge, embed keys (Steps 9, 10, 14).
- Reassign-of-referenced-key from the assistant side (already lives on `POST /integrations/ai/providers/reassign` from Step 1).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/ai_assistants/schemas.py` | **EDIT** — flesh out from Step 5's placeholder |
| `API/src/app/core/ai_assistants/service.py` | **NEW** |
| `API/src/app/core/ai_assistants/router.py` | **NEW** |
| `API/src/app/core/ai_assistants/data_access.py` | **EDIT** — flesh out from Step 5's stubs |
| `API/src/app/main.py` | **EDIT** — register router |
| `API/tests/ai_assistants/test_crud.py` | **NEW** |
| `API/tests/ai_assistants/test_rbac.py` | **NEW** |
| `API/tests/ai_assistants/test_timing_and_isolation.py` | **NEW** |

**~8 files. ~500 lines.**

## Plan

1. Schemas first. `extra='forbid'` on all write schemas — surfaces attempts to write disallowed fields as 422.
2. Service — cross-org key validation is the tricky bit: query key without RLS (via a dedicated session or by explicitly bypassing RLS session var), compare `org_id`, then return 404. Alternative: keep RLS on and just query with `WHERE key_id = :id AND org_id = :caller_org` — if 0 rows, 404. Simpler and just as safe. Use the simpler pattern.
3. OCC — SQLAlchemy's `version_id_col` on the model may already do this from Step 5; if so, catch `StaleDataError` and translate to 409. Otherwise, explicit `UPDATE ... WHERE version = :v RETURNING`.
4. Timing-safe 404 — test measures response-time mean over 1000 samples for `nonexistent_id` vs `other_org_id`; asserts within 20% of each other.
5. Router uses standard permission dependency pattern (grep other modules for `require_permission(`).
6. `POST /archive` returns 204; `DELETE ?confirm=true` returns 204; both are idempotent.

## DB changes / migrations

None (all tables exist from Step 5).

## Tests

- `AiAssistantCreate` with `{"org_id": "..."}` in body returns 422 (`extra='forbid'`).
- `PATCH` with wrong `version` returns 409.
- `PATCH` changing `instructions` writes an audit row with old + new values.
- `GET /ai-assistants/{other_org_id}` returns 404 with body identical to `GET /ai-assistants/{random-uuid}` (same JSON body, same status).
- Timing test: 1000-sample mean of `GET /ai-assistants/{other_org_id}` within ±20% of `GET /ai-assistants/{random-uuid}` (both hit DB).
- `POST /ai-assistants` with `key_id` from another org returns 404 (not 403).
- List paginates.
- RBAC: user with only `ai_assistants.view` calling `POST` gets 403; user with `.manage` succeeds.
- Delete cascades: after delete, knowledge + chunks + audit are gone (FK); `tbl_ai_assistant_message_meta` rows have `assistant_id = NULL`.
- Delete without `?confirm=true` returns 400 with actionable message.

## Smoke

```
1. curl POST /ai-assistants with valid key_id
   {"name":"My First Assistant","key_id":"<K1>","model":"gpt-4o-mini","temperature":0.5}
   → 201, version=1.
2. curl PATCH /ai-assistants/{id} {"instructions":"You help customers.","version":1}
   → 200, version=2.
3. curl PATCH /ai-assistants/{id} with version=1 → 409.
4. curl GET /ai-assistants → list contains new assistant.
5. Instruction audit: SELECT * FROM tbl_ai_assistant_instruction_audit → 1 row for the PATCH.
```

## Risks

- Timing-parity test can be flaky in noisy CI; mitigation is a wide (20%) tolerance and repeat-on-fail.
- OCC via `version_id_col` requires the model to declare `__mapper_args__ = {"version_id_col": version}` — verify from Step 5 output; otherwise wire manually.

## Self-check (10 rules)

`core/ai_assistants/` only. ✓ org_id filter on every query; timing-safe 404. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar (Step 5). ✓ Permissions enforced. ✓ pack.yaml untouched. ✓ 8 files / ~500 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 6 — Assistant CRUD service + router (guards, OCC, mass-assignment-safe)
Files: 8
Verify: create/read/update/archive/delete via curl; OCC 409 on stale version;
        cross-org key_id 404; timing-parity test passes; audit log written.
Tests: ~12 pytest cases including timing-parity.
Awaiting "proceed".
```
