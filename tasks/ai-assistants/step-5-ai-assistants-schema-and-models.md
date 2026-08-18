# Step 5 — AI Assistants schema + models + permissions + module registration

**Goal:** Land the foundation for `core/ai_assistants/` — four new tables, extend two existing tables (`tbl_embed_keys`, `tbl_conversations`), register sidebar module + permissions, wire Step 1's `reassign_provider_key` stub to a real bulk UPDATE. No service / router / runtime yet — those land in Steps 6, 9, 10.
**Status:** Pending
**Depends on:** Step 1 (`tbl_ai_provider_keys`), Step 4 (pgvector extension + `VECTOR` type).

---

## Scope

In-scope:

- Migration `<ts>_ai_assistants_schema.py` — four NEW tables + two ALTERs + one ENUM.
  - **NEW `tbl_ai_assistants`**:
    - `id`, `org_id`, `name` text, `description` text nullable, `status` ENUM (`draft` / `active` / `archived`) default `draft`, `key_id` UUID FK `tbl_ai_provider_keys.id` RESTRICT, `model` text (e.g. `gpt-4o-mini`), `temperature` numeric(3,2) default 0.5, `instructions` text (system prompt; nullable during draft), `stop_keywords` text[] default `{}`, `retry_attempts` int default 0, `fallback_message` text default `'I'm sorry, I can't help with that right now.'`, `allowed_domains` text[] default `{}` (for output URL sanitiser — empty = strip all URLs on public embed), `output_sanitizer_enabled` bool default true, `budget_cap_override_usd` numeric(10,4) nullable (per-assistant override; null = use org default), `version` int default 1 (optimistic concurrency), `created_by_user_id` UUID nullable FK `tbl_users.id` **ON DELETE SET NULL**, `interface_config` JSONB default `'{}'` (header text, subheader, initial messages, powered-by-toggle, footer — Step 12 populates), `styling_config` JSONB default `'{}'` (theme, shape, colours, profile picture path — Step 13 populates), audit cols. Unique `(org_id, lower(name))`. Index `(org_id, status)`.
  - **NEW `tbl_ai_assistant_knowledge`**:
    - `id`, `org_id`, `assistant_id` UUID FK `tbl_ai_assistants.id` **ON DELETE CASCADE**, `source_type` ENUM (`file` / `text` / `url`), `original_filename` text nullable (display only, NEVER used as path), `body_text` text nullable (for `text` source), `url` text nullable (for `url` source), `content_hash` bytea (32 bytes; dedup within assistant), `mime_type` text nullable, `size_bytes` int nullable, `status` ENUM (`pending` / `processing` / `ready` / `failed_no_text` / `failed_stuck` / `failed_ingest` / `pending_delete` / `pending_cancel`) default `pending`, `status_message` text nullable, `progress_pct` int default 0, `heartbeat_at` timestamp nullable (Celery ingest writes; Step 17 reaps if stale), `chunk_count` int default 0, audit cols. Unique `(assistant_id, content_hash)` — enforces dedup.
  - **NEW `tbl_ai_assistant_chunks`**:
    - `id`, `org_id`, `knowledge_id` UUID FK `tbl_ai_assistant_knowledge.id` **ON DELETE CASCADE**, `chunk_index` int, `text` text, `embedding` `VECTOR(1536)`, `token_count` int, `status` ENUM (`ready` / `pending_delete`) default `ready`, audit cols. Composite HNSW index: `CREATE INDEX ix_chunks_org_embedding_hnsw ON tbl_ai_assistant_chunks USING hnsw (embedding vector_cosine_ops) WHERE status = 'ready';` — HNSW is a global index, but the query `WHERE org_id=$1 ... ORDER BY embedding <=> $2` plans through it with a supporting b-tree on `(org_id, status)`. Add that b-tree explicitly: `ix_chunks_org_status`.
  - **NEW `tbl_ai_assistant_message_meta`**:
    - `message_id` UUID PK FK `tbl_messages.id` **ON DELETE CASCADE**, `org_id`, `assistant_id` UUID FK `tbl_ai_assistants.id` **ON DELETE SET NULL** (keeps history when assistant deleted), `model` text, `prompt_tokens` int, `completion_tokens` int, `total_tokens` int, `cost_usd` numeric(10,6), `cost_status` ENUM (`pending_llm_confirm` / `confirmed` / `reconciled` / `failed`) default `pending_llm_confirm` (outbox pattern for cost accounting), `provider_error` text nullable, `retrieved_chunk_ids` UUID[] default `{}` (audit trail for which knowledge answered). Index `(org_id, assistant_id, created_at DESC)`.
  - **NEW `tbl_ai_assistant_instruction_audit`**:
    - `id`, `org_id`, `assistant_id` FK CASCADE, `changed_by_user_id` UUID FK `tbl_users.id` SET NULL, `field_name` text (`instructions` / `model` / `temperature` / etc.), `old_value` text nullable, `new_value` text nullable, `changed_at` timestamp default now(). Index `(assistant_id, changed_at DESC)`.
  - **ALTER `tbl_embed_keys`**:
    - Add column `resource_type` text NOT NULL default `'lead_form'` (values `'lead_form'` / `'ai_assistant'` — Postgres CHECK constraint; not an ENUM to keep existing rows working; enum could be added later).
    - Add column `resource_id` UUID nullable (nullable so existing lead-form rows don't need backfill; new ai_assistant rows require it — service enforces).
    - Index `(resource_type, resource_id)`.
    - Backfill existing rows: `UPDATE tbl_embed_keys SET resource_type='lead_form' WHERE resource_type IS NULL;` (already default).
  - **ALTER `tbl_conversations`** (if it has a `channel` column already):
    - No schema change if `channel` is a free text or text-like column. If it's an ENUM, migration ALTERs the ENUM to add `'ai_widget'`. Step 5's Plan phase inspects [API/src/app/core/conversations/models.py](API/src/app/core/conversations/models.py) first to confirm.
- Two new ENUMs: `ai_assistant_status`, `knowledge_source_type`, `knowledge_status`, `chunk_status`, `cost_status`.
- SQLAlchemy models in `core/ai_assistants/models.py` — `AiAssistant`, `AiAssistantKnowledge`, `AiAssistantChunk` (with `pgvector.sqlalchemy.Vector` column), `AiAssistantMessageMeta`, `AiAssistantInstructionAudit`. All `TenantScoped` except `AiAssistantMessageMeta` (keyed on `message_id`, `TenantScoped` still applies via `org_id`).
- `core/ai_assistants/__init__.py`, `core/ai_assistants/schemas.py` (placeholder Pydantic stubs — Step 6 fills), `core/ai_assistants/data_access.py` (placeholder queries — `get_assistant`, `count_by_key_id` for Step 1's reassign to call).
- `core/ai_assistants/module.py` — `ModuleDescriptor(id="ai_assistants", name="AI Assistants", icon="sparkles", section="Automation", menu_position=<between Workflows and Chatbots>, permissions=list(ALL_KEYS), frontend_route="/user/ai-assistants", ...)`.
- `core/ai_assistants/permissions.py` — registers `ai_assistants.view`, `ai_assistants.manage` (default Owner+Admin+Manager; Employee opt-in per role editor).
- **Wire Step 1's `reassign_provider_key`** — replace the `NotImplementedError` stub in [API/src/app/core/integrations/ai/service.py](API/src/app/core/integrations/ai/service.py) with a bulk UPDATE via `data_access.reassign_keys(from_key_id, to_key_id, org_id)` — hits `tbl_ai_assistants.key_id` in one statement inside the caller's transaction. Also wire `count_by_key_id` for the delete-block check.
- **Add exception-list entries** to [API/tests/test_layered_architecture_convention.py](API/tests/test_layered_architecture_convention.py) for `core/ai_assistants/runtime.py` and `core/ai_assistants/ingest.py` (files not yet present — pin-test's exception list lands here so Steps 9/10 don't break CI).

Out of scope:
- Service beyond stub queries (Step 6).
- Router (Step 6).
- Any UI (Step 7+).
- Runtime / ingest logic (Steps 9, 10).

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_ai_assistants_schema.py` | **NEW** |
| `API/src/app/core/ai_assistants/__init__.py` | **NEW** |
| `API/src/app/core/ai_assistants/models.py` | **NEW** |
| `API/src/app/core/ai_assistants/schemas.py` | **NEW** — placeholder |
| `API/src/app/core/ai_assistants/data_access.py` | **NEW** — stubs |
| `API/src/app/core/ai_assistants/module.py` | **NEW** |
| `API/src/app/core/ai_assistants/permissions.py` | **NEW** |
| `API/src/app/core/integrations/ai/service.py` | **EDIT** — wire reassign + count_by_key_id |
| `API/src/app/core/integrations/ai/data_access.py` | **EDIT** — add `reassign_keys` bulk UPDATE |
| `API/src/app/main.py` | **EDIT** — side-effect import of models |
| `API/tests/test_layered_architecture_convention.py` | **EDIT** — add runtime.py + ingest.py to exception list |
| `API/tests/ai_assistants/test_schema.py` | **NEW** |
| `API/tests/ai_assistants/test_reassign.py` | **NEW** |

**~13 files. ~600 lines.** Over — five tables + two ALTERs + permission/module wiring + Step 1 completion all in one step. Splitting would leave Step 1 with a broken reassign forever.

## Plan

1. Read `core/conversations/models.py` to determine `channel` column type before writing the ALTER.
2. Migration writes tables in dependency order: assistants → knowledge → chunks → message_meta → audit. ENUMs first. Composite HNSW index last (after data would be inserted, but there's no data yet).
3. Models with `Vector` column: `embedding = mapped_column(Vector(1536))`.
4. `tbl_embed_keys` ALTER: CHECK constraint `resource_type IN ('lead_form', 'ai_assistant')`; migration backfills existing rows.
5. `data_access.reassign_keys` — single `UPDATE tbl_ai_assistants SET key_id = :to_id WHERE org_id = :org_id AND key_id = :from_id RETURNING id;` — service captures RETURNING count for observability.
6. Module descriptor `menu_position` set between Workflows and Chatbots — grep their current positions in `core/workflows/module.py` and `core/chatbots/module.py`.

## DB changes / migrations

Five new tables (assistants, knowledge, chunks, message_meta, instruction_audit) + two ALTERs (`tbl_embed_keys` cols; `tbl_conversations.channel` if enum). Five new ENUMs. Reversible.

## Tests

- Migration up + down clean.
- All new tables have `org_id` + RLS policies.
- `tbl_embed_keys` existing rows retain `resource_type='lead_form'` after migration.
- Deleting an assistant cascades knowledge + chunks + audit (via FK) in one transaction. `tbl_conversations` rows survive (message_meta `assistant_id` SET NULL, `tbl_messages` rows untouched).
- Deleting a user sets `created_by_user_id` NULL on their assistants.
- Reassign: create 3 assistants pointing at key A, call `reassign_provider_key(A, B)`, verify all 3 point at B and `delete(A)` succeeds.
- Cross-org reassign refused (attempting to reassign to a key in another org returns 404 with no leak).
- Optimistic-concurrency: incrementing `version` on update; conflicting update raises `StaleDataError` (SQLAlchemy).
- `count_by_key_id` returns correct count.

## Smoke

```
1. run.cmd upgrade — 5 tables + 2 ALTERs applied.
2. \d tbl_ai_assistants — shows all columns + FKs.
3. \d tbl_embed_keys — shows resource_type + resource_id.
4. Sidebar (once frontend module-service refreshed) — "AI Assistants" appears
   in Automation section between Workflows and Chatbots.
```

## Risks

- The `channel` column extension depends on the existing conversations model's shape. Plan phase inspects first.
- HNSW index build on an empty table is instant; on a real prod DB with data, this DDL is fine because no chunks exist yet.
- Adding `resource_id` as nullable means service enforcement is critical (Step 14 enforces NOT NULL for `ai_assistant` rows at the service layer; DB CHECK could be added later once no lead-form rows have NULL either).

## Self-check (10 rules)

`core/ai_assistants/` + extension of `core/integrations/`, `core/embed/`, `core/conversations/`. ✓ Rule 2: `org_id` + RLS on all 5 new tables; `tbl_embed_keys` retains its existing RLS. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ Rule 5: sidebar via `module.py`. ✓ Rule 6: two new permission keys registered. ✓ pack.yaml untouched. ✓ 13 files / ~600 lines — over but justified. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 5 — AI Assistants schema + models + permissions + module registration
Files: 13
Verify: migration up/down; cascade + SET NULL behaviour; reassign works;
        sidebar shows AI Assistants between Workflows and Chatbots.
Tests: ~10 pytest cases.
Awaiting "proceed".
```
