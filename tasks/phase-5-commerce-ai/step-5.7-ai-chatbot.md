# Step 5.7 — AI Chatbot — Conversations integration

**Goal:** Plug an LLM into Conversations. AI Handled / Needs Human flag drives whether the bot replies. Bot personality + welcome message from Settings → AI. Message review/override flow.
**Phase:** 5
**Depends on:** 3.10, 3.17
**Status:** Pending

## Scope
**In-scope:**
- New `app/core/ai/llm_client.py`:
  - `LLMClient` interface with `complete(messages: list[dict], system: str) -> str`.
  - Default impl using Anthropic Claude via `anthropic` Python SDK (claude-sonnet-4-6 default; configurable). `claude-sonnet-4-6` available because environment claims Jan 2026 cutoff; if SDK requires a specific model id, use the latest claude-sonnet at install time. Settings: `AI_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, `AI_MODEL=claude-sonnet-4-6`.
  - Prompt-cache via SDK to reduce costs.
- Conversations service hook: when an inbound message arrives AND `conversation.ai_handling=true`:
  - Build context from last N messages.
  - Add system prompt = `org_settings.ai_personality` + `ai_welcome_message` plus a structured guardrail (don't promise pricing, don't speak about competitors).
  - Get LLM response.
  - If confidence-or-keyword guardrail triggers (configurable), set `conversation.needs_human=true` and DO NOT auto-send; staff sees the suggested reply with Approve/Edit/Reject.
  - Else send via channel adapter; persist as outbound with `sender_user_id=NULL` and a flag `ai_generated=true`.
- New columns on `messages`: `ai_generated bool default false`. Migration `0029_messages_ai_flags.py`.
- Endpoints: `POST /conversations/{id}/ai-suggest` (manual trigger), `POST /messages/{id}/approve-ai` (sends a held suggestion), `POST /messages/{id}/reject-ai`.
- Frontend updates: AI Handled badge already present; add "Suggested by AI — Approve / Edit / Reject" inline in compose bar when a held suggestion exists.

## Files to touch
- `api/app/core/ai/{__init__,llm_client,policies}.py` (created)
- `api/app/core/conversations/service.py` (modified — AI hook)
- `api/alembic/versions/0029_messages_ai_flags.py` (created)
- `app/src/app/features/user/core/conversations/compose-bar.component.ts/.html` (modified — Approve/Edit/Reject)

## Plan
1. LLM client with Anthropic SDK + prompt caching enabled.
2. Policies module: configurable guardrails (regex/keyword based), confidence threshold (length + uncertainty proxy).
3. Hook on inbound message intake (in `conversations.service`) when `ai_handling=true`.
4. Frontend: when message has `ai_generated=true AND not yet sent`, render approval bar.

## Tests to add
- `tests/test_ai_hook.py` — fake LLM returns canned response; flow works.
- `tests/test_ai_guardrail.py` — when keyword "price" hits, suggestion held for review.

## Verification checklist
**Backend:**
- enable ai_handling on a conversation. Send inbound → outbound AI message generated and either auto-sent or held.
**Frontend:**
- held suggestion shows Approve/Edit/Reject inline.

## Self-check (10 rules)
- [ ] org_id scoping respected.
- [ ] AI personality from settings, not hardcoded.

## Stop & report
Await "proceed" before Step 5.8.
