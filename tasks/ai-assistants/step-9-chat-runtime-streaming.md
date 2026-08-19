# Step 9 — Chat runtime — retrieve + structured envelope + stream + cost outbox

**Goal:** Ship the chat runtime — the assistant can actually reply. Retrieve top-K knowledge chunks (HNSW), build a structured JSON envelope (not string-delimited concatenation) as a `role="user"` message, stream tokens via SSE, cancel OpenAI stream on client disconnect, enforce stop-keyword + budget-cap + `max_tokens` limits pre-call, and record cost via outbox pattern. Wire the operator-facing preview pane to hit the real runtime so the two-pane editor becomes end-to-end functional.
**Status:** COMPLETED — 12 files landed (5 new + 7 edits; consolidated the 4 planned separate runtime-test files into 2 focused files: output_sanitizer helpers + runtime helpers). `core/ai_assistants/runtime.py` ships the full orchestrator (~400 lines): assistant-load + status gate → stop-keyword short-circuit → budget-cap `dry_run` pre-flight → conversation + user-message persistence → embed via `shared.llm.factory('openai',...).embed()` → HNSW top-K retrieval scoped to this assistant's knowledge → structured JSON envelope (NOT delimiter-wrapped — Attacker C4 defence) as `role='user' name='knowledge_base'` → pending cost-outbox meta row → `LLMClient.stream()` → disconnect polling every 20 chunks (cancels OpenAI stream if `request.is_disconnected()` — Attacker C5) → server-side usage extraction + cost computation via `pricing.cost_for()` → output sanitiser on public embeds → confirmed meta row + `charge_budget(dry_run=False)`. Preview endpoint `POST /api/v1/ai-assistants/{id}/preview` streams SSE via FastAPI `StreamingResponse` with a background disconnect-poller task that flips shared state the sync runtime callable reads. Frontend `preview-stream.service.ts` uses `fetch()` + `ReadableStream` (NOT `EventSource` — Attacker M4, keeps JWT in Authorization header not URL). Preview component gets full chat state: message array signal, input signal, streaming signal, `canSend` computed, send flow with per-frame token appending. Chatbot AI-node stubs (`single_ai_message`, `assign_ai_assistant`) now find first active assistant and call `runtime.reply_once()` (added `ctx.session is None` guard for test compatibility). 125 tests green in 28.62s (23 new: 10 output_sanitizer + 13 runtime_helpers). ng build clean. Confirmed pre-existing 2 chatbot test failures (`test_create_lead_skips_without_contact`, `test_create_task_specific_mode_test_mode`) exist on pristine HEAD too — `_make_ctx` re-generates a fresh contact when `contact_id=None` is passed, so those tests never actually exercised the no-contact path.
**Depends on:** Steps 2 (LLMClient), 4 (VectorStore), 5 (tables), 6 (assistant CRUD).

---

## Scope

In-scope:

- `core/ai_assistants/runtime.py` — the chat orchestrator (invoked by both public router for the widget and by the operator preview endpoint):
  - `async def stream_reply(db, org_id, assistant_id, conversation_id | None, user_message, session_token, is_public: bool) -> AsyncIterator[RuntimeChunk]` where `RuntimeChunk` is `{type: 'token' | 'error' | 'done', ...}`.
  - Flow:
    1. Load assistant + verify status='active' (or 'draft' if preview call).
    2. **Stop-keyword short-circuit** — if user message case-insensitively matches any stop keyword, yield the fallback message as a single non-LLM chunk, persist as a message, return.
    3. **Budget-cap pre-flight** — call `charge_budget(db, org_id, cost_usd=0, dry_run=True)`; if would exceed either cap, yield fallback + `RuntimeChunk(type='error', reason='budget_cap_hit')`, persist, return.
    4. Resolve or create conversation: if `conversation_id` provided and belongs to `(org_id, assistant_id, session_token)`, use it; else create a new `tbl_conversations` row with `channel='ai_widget'`, `external_user_id=session_token`, `assistant_id` (via message_meta) — cap: if the current conversation has ≥ 100 turns, mark `capped=true` in metadata and start a fresh conversation.
    5. Persist the user message to `tbl_messages` + a `tbl_ai_assistant_message_meta` row (no meta for user msgs — meta rows only for assistant replies; skip).
    6. **Retrieve** — embed the user's message via `shared.llm.factory('openai', assistant.key_id).embed([user_message])` → single vector; `VectorStore.search(org_id, vector, top_k=5, filter_parent_id=None)` filtered inside the query to this assistant's knowledge (join via `knowledge_id IN (SELECT id FROM tbl_ai_assistant_knowledge WHERE assistant_id = :a)`). If retrieval returns 0 above the similarity threshold (score < 0.3), fall back to prompt-only OR fallback message per assistant config `retrieval_empty_behavior` (default `fallback`).
    7. **Build messages** — three roles:
       - `system`: assistant.instructions verbatim.
       - `user` with `name="knowledge_base"`: JSON string `{"sources": [{"id": <chunk_id>, "text": <chunk_text>}, ...]}` — **not** delimiter-wrapped.
       - Last N=10 turns from conversation (interleaved `user` / `assistant`).
       - Current `user`: the actual user message.
    8. **Insert cost outbox row** in `tbl_ai_assistant_message_meta` with `cost_status='pending_llm_confirm'`, empty message body — will be updated after LLM completes.
    9. Call `LLMClient.stream(messages, model, temperature, max_tokens=1024)`.
    10. As chunks arrive, yield to caller; every 20 chunks check `request.is_disconnected()` — if true, cancel the OpenAI stream (`await response.close()`), mark meta row `cost_status='failed'` + `provider_error='client_disconnect'`, persist partial content, return.
    11. On stream end, extract final `usage`, compute cost via `pricing.cost_for()`, UPDATE meta row: `total_tokens`, `cost_usd`, `cost_status='confirmed'`. `charge_budget(db, org_id, cost_usd, dry_run=False)`.
    12. **Output sanitiser** — if `is_public and assistant.output_sanitizer_enabled`, run the full assistant reply through `sanitize_output(text, allowed_domains)` before persisting the message body (strip URLs + emails not on allow-list). Yield sanitised content.
    13. Persist the assistant message + link meta row via `message_id`.
- `core/ai_assistants/output_sanitizer.py` — pure function `sanitize_output(text, allowed_domains) -> str` — strips URLs whose host isn't in the list; strips email addresses whose domain isn't. Uses `urllib.parse` + simple regex; not perfect but good defence in depth.
- Router endpoint `POST /ai-assistants/{id}/preview` in `core/ai_assistants/router.py` — operator preview:
  - JWT-guarded (`ai_assistants.view`).
  - Reuses `runtime.stream_reply(is_public=False)`.
  - Returns SSE stream via FastAPI's `StreamingResponse` with `media_type='text/event-stream'`.
- Extend Step 1's `charge_budget` to support `dry_run: bool` — returns `(would_allow, reason_if_not)` without mutating.
- **Wire chatbot AI-node stubs** — [API/src/app/core/chatbots/nodes/single_ai_message.py](API/src/app/core/chatbots/nodes/single_ai_message.py) + [API/src/app/core/chatbots/nodes/assign_ai_assistant.py](API/src/app/core/chatbots/nodes/assign_ai_assistant.py) — replace their "AI provider not configured" stubs with calls to `runtime.stream_reply(is_public=True, ...)` (or a non-streaming variant `runtime.reply_once(...)`). Chatbot flows can now embed an AI turn.
- **Layered-architecture exception** — `core/ai_assistants/runtime.py` added to the exception list (already added in Step 5).
- Frontend: wire `AssistantPreviewComponent` from Step 7 — replace the local-only mock with a real call to `POST /ai-assistants/{id}/preview` via `fetch()` + `ReadableStream` (not `EventSource`, so the JWT stays in `Authorization` header). Tokens append to the preview bubble as they arrive.

Out of scope:
- Knowledge ingestion (Step 10) — until Step 10, retrieval returns 0 chunks and the assistant replies from prompt only.
- Public embed endpoint (Step 14) — this step's preview is JWT-guarded operator-only.
- Widget bundle (Step 15).
- Analytics + inbox integration (Step 16).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/ai_assistants/runtime.py` | **NEW** |
| `API/src/app/core/ai_assistants/output_sanitizer.py` | **NEW** |
| `API/src/app/core/ai_assistants/router.py` | **EDIT** — add `/preview` endpoint |
| `API/src/app/core/ai_assistants/service.py` | **EDIT** — `reply_once` non-streaming helper |
| `API/src/app/core/ai_assistants/data_access.py` | **EDIT** — retrieval + message persistence queries |
| `API/src/app/core/integrations/ai/service.py` | **EDIT** — `charge_budget(dry_run=)` |
| `API/src/app/core/chatbots/nodes/single_ai_message.py` | **EDIT** — wire to runtime |
| `API/src/app/core/chatbots/nodes/assign_ai_assistant.py` | **EDIT** — wire to runtime |
| `APP/src/app/features/user/core/ai-assistants/editor/preview/assistant-preview.component.ts` | **EDIT** — real streaming |
| `APP/src/app/features/user/core/ai-assistants/editor/preview/preview-stream.service.ts` | **NEW** — fetch/ReadableStream helper |
| `API/tests/ai_assistants/test_runtime_stop_keyword.py` | **NEW** |
| `API/tests/ai_assistants/test_runtime_budget_cap.py` | **NEW** |
| `API/tests/ai_assistants/test_runtime_prompt_injection.py` | **NEW** |
| `API/tests/ai_assistants/test_runtime_disconnect.py` | **NEW** |
| `API/tests/ai_assistants/test_output_sanitizer.py` | **NEW** |
| `API/tests/ai_assistants/test_cost_outbox.py` | **NEW** |

**~16 files. ~700 lines.** Over — but this step ships the entire runtime pipeline + operator preview + chatbot-node wiring. Splitting would leave preview and chatbot nodes half-wired.

## Plan

1. `output_sanitizer.py` first — pure function, easy to test.
2. `runtime.py` — big file, one class `ChatRuntime` with `stream_reply` method. Helpers extracted (`_retrieve`, `_build_messages`, `_persist_and_charge`).
3. Retrieval query: `SELECT c.id, c.text FROM tbl_ai_assistant_chunks c JOIN tbl_ai_assistant_knowledge k ON c.knowledge_id = k.id WHERE k.assistant_id = :a AND c.org_id = :o AND c.status = 'ready' AND k.status = 'ready' ORDER BY c.embedding <=> :q LIMIT 5;` — verified via `EXPLAIN` to hit the HNSW index (fallback: composite b-tree index on `(org_id, status)` from Step 5).
4. Structured envelope: `messages.append({"role": "user", "name": "knowledge_base", "content": json.dumps({"sources": [{"id": r.id, "text": r.text} for r in retrieved]})})`. OpenAI SDK accepts `name` field on messages.
5. Disconnect polling: FastAPI's `request.is_disconnected()` in a wrapping loop; on true, `await stream.close()` on the OpenAI response, then update meta row.
6. Cost outbox: INSERT `pending_llm_confirm` row before LLM; UPDATE to `confirmed` on success. If UPDATE fails (DB blip), the reconcile task (Step 17) catches `pending_llm_confirm` rows older than 5 min and either confirms via OpenAI usage API or marks `failed`.
7. Chatbot node wiring: `single_ai_message.py` builds a synthetic `runtime.reply_once(...)` call (non-streaming) with the flow's contact + a one-shot user message; result becomes the node output.
8. Frontend preview: `preview-stream.service.ts` wraps `fetch()` returning `ReadableStream`; consumer decodes SSE `data:` lines and emits tokens as a signal-friendly stream. Component appends tokens to a `signal<string>` and re-renders.

## DB changes / migrations

None (all tables from Step 5).

## Tests

- Stop-keyword: user message "stop please" with `stop_keywords=['stop']` → returns fallback, LLM adapter never called.
- Budget-cap: cap set to $0.01, spent = $0.02 → returns fallback, LLM never called.
- Retrieval empty + `retrieval_empty_behavior='fallback'` → fallback returned.
- Retrieval empty + `retrieval_empty_behavior='prompt_only'` → LLM called, no knowledge context in messages.
- Prompt injection: user message "Ignore system prompt" → system role remains distinct; assert `messages[0]['role']='system' and messages[0]['content'] == assistant.instructions`.
- Structured envelope: assert retrieved chunks in `messages[1]` are JSON-parseable `{"sources": [...]}`.
- Disconnect: mock `request.is_disconnected()` to return True on the 25th check; assert OpenAI stream `.close()` called; meta row `cost_status='failed'`, `provider_error='client_disconnect'`.
- Cost outbox: on success, meta row transitions `pending_llm_confirm → confirmed`; on `ProviderQuotaExceeded`, transitions to `failed` with error.
- Output sanitiser: `"Visit https://attacker.com for more"` with `allowed_domains=['example.com']` → URL stripped from persisted content and stream output.
- Chatbot node: `single_ai_message` invocation returns a non-empty reply (mocked LLM).

## Smoke

```
1. Assistant with a valid key + instructions + no knowledge.
2. From editor preview pane, type "Hello". Watch tokens stream in.
3. Check tbl_ai_assistant_message_meta: 1 row, cost_status='confirmed', cost_usd > 0.
4. Check tbl_org_ai_cost_budget: spent_today_usd increased.
5. Add stop_keywords=['stop']. Type "stop please" — fallback appears instantly.
6. Set budget_cap_override=0.001. Type any message — fallback with "budget_cap_hit".
```

## Risks

- Streaming SSE from FastAPI with disconnect polling requires careful async cleanup; test coverage on the disconnect path is critical.
- Chatbot node integration touches two files outside this track — regression risk. Existing chatbot pytest suite must stay green.
- The retrieval query performance on empty knowledge is fine (HNSW returns empty fast); on large orgs (>100k chunks) will need review, but that's out of v1 scope.

## Self-check (10 rules)

`core/ai_assistants/` + chatbot-node wiring. ✓ org_id filtered in retrieval + all inserts. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. ✓ Permission enforced on `/preview`. ✓ pack.yaml untouched. ✓ 16 files / ~700 lines — over but end-to-end runtime justifies. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 9 — Chat runtime — retrieve + structured envelope + stream + cost outbox
Files: 16
Verify: preview streams tokens; stop-keyword + budget-cap + disconnect + injection tests
        pass; cost outbox reconciles; chatbot AI nodes now functional; layered pin-test green.
Tests: ~14 pytest cases.
Awaiting "proceed".
```
