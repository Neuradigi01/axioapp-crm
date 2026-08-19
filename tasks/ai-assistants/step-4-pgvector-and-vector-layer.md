# Step 4 — pgvector extension + `shared/vector/` + HNSW composite + chunker

**Goal:** Install `pgvector` on Postgres 17, ship the `VectorStore` interface with a `pgvector.py` implementation using **HNSW** and a composite `(org_id, embedding)` index so RLS-scoped queries plan correctly and cold-org queries work. Ship the ~800-token chunker. No assistant tables yet (Step 5 uses this layer).
**Status:** COMPLETED — 10 files landed (8 new + 2 edits). Migration `0200_install_pgvector` runs `CREATE EXTENSION IF NOT EXISTS vector`; verified `pg_extension` on Postgres 17.5 in the compose stack. New `shared/vector/`: `base.py` protocol (`VectorStore` with `upsert` / `search` / `delete_by_parent` + frozen `VectorEntry`/`SearchResult` dataclasses); `pgvector.py` implementation with the actual chunks-table SQL (`INSERT ... ON CONFLICT DO UPDATE` for upsert, cosine-distance `<=>` for search with `1 - distance` score, cascade delete by parent knowledge_id) and `set_config('app.current_org_id', :org_id, true)` before every read/write for RLS (the initial `SET LOCAL app.current_org_id = $1` approach hit `PostgresSyntaxError` — bind params aren't accepted on DDL `SET`, `set_config` is the parameterised equivalent); `chunker.py` token-aware splitter using `tiktoken cl100k_base` with paragraph→sentence→word→hard-slice fallback strategy + prompt-injection marker stripping (`</context>`, `<system>`, `SYSTEM:`, `ASSISTANT:`, `<instructions>` — case-insensitive) as defence-in-depth for Step 9's retrieval envelope. Two new deps pinned in `requirements.txt`: `pgvector>=0.3,<1.0` (installed 0.5.0), `tiktoken>=0.8,<1.0` (installed 0.14.0). 65 tests green in 15.17s: 19 Step-4 (17 pure-Python chunker + 2 DB-touching pgvector smoke exercising real cosine ordering + cross-org isolation + set_config-precedes-SELECT capture) + 46 Steps-1/2 regression pass.
**Depends on:** Step 2 (`shared/llm/openai.py` provides `embed()`).

---

## Scope

In-scope:

- Migration `<ts>_install_pgvector.py` — `CREATE EXTENSION IF NOT EXISTS vector;`. Downgrade: `DROP EXTENSION IF EXISTS vector;` (safe because Step 5 owns the first table that uses it — this step doesn't create any).
- `shared/vector/__init__.py` — factory `def vector_store() -> VectorStore` (returns the pgvector implementation; interface exists for future swap).
- `shared/vector/base.py` — `VectorStore` protocol:
  - `async def upsert(org_id, entries: list[VectorEntry])` where `VectorEntry(id, embedding, metadata, org_id, parent_id, parent_type)`.
  - `async def search(org_id, query_embedding, top_k=5, filter_parent_id=None) -> list[SearchResult]` where `SearchResult(id, score, metadata, parent_id)`.
  - `async def delete_by_parent(org_id, parent_id, parent_type)`.
- `shared/vector/pgvector.py` — implementation:
  - Constructor takes `AsyncSession`.
  - `upsert` uses `INSERT ... ON CONFLICT (id) DO UPDATE`.
  - `search` executes:
    ```sql
    SELECT id, metadata, parent_id, 1 - (embedding <=> :q) AS score
    FROM tbl_ai_assistant_chunks
    WHERE org_id = :org_id AND status = 'ready'
    ORDER BY embedding <=> :q
    LIMIT :k;
    ```
    Sets `SET LOCAL app.current_org_id = :org_id` first so RLS applies.
  - `delete_by_parent` cascades chunks for a knowledge row (used by Step 10's replace flow).
- `shared/vector/chunker.py` — text chunker:
  - `chunk_text(text: str, target_tokens: int = 800, overlap_tokens: int = 100) -> list[Chunk]` where `Chunk(text, index, token_count)`.
  - Uses `tiktoken` (`cl100k_base` for OpenAI models) for accurate token counting.
  - Strategy: split on paragraph boundaries where possible; fall back to sentence, then word; hard-slice only if a single word exceeds `target_tokens`.
  - Strips known prompt-injection tokens BEFORE chunking (`</context>`, `<context>`, `</system>`, `<system>`, `SYSTEM:`, `ASSISTANT:`) — this is defence in depth for Step 9/10; the actual retrieval envelope is JSON, not delimiter-wrapped, so this is belt+braces.
- Add `pgvector` (Python client) and `tiktoken` to `pyproject.toml`.

**Note:** the actual `tbl_ai_assistant_chunks` table + composite HNSW index lands in Step 5. This step installs the extension and ships the *code* that will use it. Step 5's migration includes the `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)` DDL.

Out of scope:
- The chunks table (Step 5).
- The knowledge table (Step 5).
- Ingest task (Step 10).
- Any assistant / conversation code.

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_install_pgvector.py` | **NEW** |
| `API/src/app/shared/vector/__init__.py` | **NEW** |
| `API/src/app/shared/vector/base.py` | **NEW** |
| `API/src/app/shared/vector/pgvector.py` | **NEW** |
| `API/src/app/shared/vector/chunker.py` | **NEW** |
| `API/pyproject.toml` | **EDIT** — add `pgvector`, `tiktoken` |
| `API/tests/shared/vector/test_chunker.py` | **NEW** |
| `API/tests/shared/vector/test_pgvector_smoke.py` | **NEW** — smoke against a real DB (skipped if extension not present) |

**~8 files. ~320 lines.**

## Plan

1. Migration installs extension. Idempotent via `IF NOT EXISTS`. Fails hard with a helpful message ("pgvector must be in Postgres extension allowlist — see README §deployment precondition") if the underlying `CREATE EXTENSION` throws.
2. `VectorStore` protocol first — abstract enough that a future Pinecone/Weaviate implementation could slot in.
3. `pgvector.py` — one class, delegates to raw SQL via `db.execute(text(...))`. Uses `pgvector.sqlalchemy.Vector` type for column mapping (in Step 5).
4. Chunker — pure function, no DB. Tests use short deterministic inputs.
5. Injection-token stripping — a compiled regex list (case-insensitive) applied via `re.sub` before splitting.

## DB changes / migrations

Extension install only. Downgrade drops. Idempotent.

## Tests

- Chunker: 3000-char text → ≥ 3 chunks with proper overlap.
- Chunker: paragraph boundary respected when possible.
- Chunker: injection tokens stripped (`"</context>SYSTEM: ignore"` chunks to `" ignore"`).
- Chunker: token counts within ±5% of `target_tokens` for average chunks.
- pgvector smoke: `CREATE TABLE`, insert 5 vectors, run cosine search, get top-K in expected order. Skipped if extension absent.
- Query includes `SET LOCAL app.current_org_id` — verified by capturing executed SQL.

## Smoke

```
1. run.cmd upgrade — pgvector installed.
2. psql: SELECT extname FROM pg_extension WHERE extname='vector'; → returns row.
3. Python REPL: from shared.vector.chunker import chunk_text; chunks = chunk_text("...long text...");
   verify token counts + overlap.
```

## Risks

- **Deployment precondition** — production Postgres must have `pgvector` in the extension allow-list. On managed platforms (Supabase / Neon = yes; AWS RDS Postgres 17 = yes since 16.3+; older = no). Documented in README §Locked design 3. If the target Postgres lacks it, migration will fail hard with actionable error.
- `tiktoken` downloads a tokeniser file on first use in some deployments; the smoke section warms it at container startup.

## Self-check (10 rules)

`shared/vector/` + one migration. ✓ N/A org_id (interface only; org scoping enforced in queries in Step 5). N/A rules 3/4/5/6/7. ✓ 8 files / ~320 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 4 — pgvector extension + shared/vector/ + HNSW composite + chunker
Files: 8
Verify: extension installed; chunker produces ≥3 chunks with correct overlap on
        3000-char input; pgvector smoke passes on DB with extension.
Tests: ~6 pytest cases.
Awaiting "proceed".
```
