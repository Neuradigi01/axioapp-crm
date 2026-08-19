"""Chat runtime for AI Assistants
(``tasks/ai-assistants`` Step 9).

The orchestrator that turns a user message into a streamed assistant
reply. Invoked from two surfaces:

  * ``POST /api/v1/ai-assistants/{id}/preview`` (Step 9 operator
    preview — JWT-guarded, ``is_public=False``).
  * ``POST /api/v1/public/ai-assistants/message`` (Step 14 public
    embed — embed-key auth, ``is_public=True``).

Flow (mirrors the step spec + Attacker/Absence review findings):

  1. Load assistant + verify it can accept traffic (draft OK for
     preview, active-only for public).
  2. **Stop-keyword short-circuit** — server-enforced (Attacker H7).
     Skips the LLM entirely.
  3. **Budget-cap pre-flight** — ``charge_budget(dry_run=True)`` so
     an out-of-hours attacker can't drain the org's OpenAI budget
     even if their message would otherwise be legal.
  4. Persist the user message (inbox integration — Attacker/Absence
     H1: everything lands in ``tbl_conversations`` + ``tbl_messages``
     so human-handoff works for free).
  5. **Retrieve** — top-K HNSW chunks scoped to this assistant's
     knowledge (empty when Step 10's ingest hasn't landed).
  6. **Build messages** — three roles: ``system`` = instructions;
     ``user`` with ``name='knowledge_base'`` carrying a structured
     JSON envelope of retrieved chunks (NOT delimiter-wrapped —
     Attacker C4 defence); current ``user`` = the actual message.
  7. **Insert cost outbox row** (``pending_llm_confirm``) BEFORE the
     LLM call.
  8. Stream tokens via ``LLMClient.stream``.
  9. Poll ``request.is_disconnected()`` every 20 tokens; on true
     cancel the OpenAI stream + mark meta ``failed`` (Attacker C5:
     abandoned tabs stop billing).
 10. On completion extract usage server-side, compute cost, UPDATE
     meta to ``confirmed``, ``charge_budget(dry_run=False)``.
 11. Output sanitiser (public embeds only) — strip URLs/emails not
     on ``assistant.allowed_domains``.
 12. Persist the final assistant message + link the meta row.

Runtime is on the layered-architecture pin-test's exception list
(added in Step 5) because it opens its own transactions to
manage the cost-outbox pattern across the async LLM call boundary.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.ai_assistants import data_access as _da
from src.app.core.ai_assistants.models import AiAssistant, AiAssistantStatus
from src.app.core.ai_assistants.output_sanitizer import sanitize_output
from src.app.core.integrations.ai import service as _budget_service
from src.app.shared.llm import LLMChunk, ProviderError, factory
from src.app.shared.llm.pricing import cost_for
from src.app.shared.llm.base import Usage

logger = logging.getLogger(__name__)

_DISCONNECT_CHECK_EVERY_N_CHUNKS = 20
_MAX_TOKENS_PER_REPLY = 1024
_TOP_K = 5
_SIMILARITY_THRESHOLD = 0.3
_EMBED_MODEL = "text-embedding-3-small"


@dataclass(frozen=True, slots=True)
class RuntimeChunk:
    """One event yielded by :meth:`ChatRuntime.stream_reply`."""

    type: Literal["token", "error", "done"]
    delta: str = ""
    reason: str | None = None
    # Only populated on the terminal chunk when the runtime completed
    # successfully — token counts + usd cost so the caller can log /
    # display without a separate round-trip.
    total_tokens: int | None = None
    cost_usd: Decimal | None = None


def _matches_stop_keyword(message: str, stop_keywords: list[str]) -> bool:
    lowered = message.strip().lower()
    for kw in stop_keywords:
        if not kw:
            continue
        if kw.lower() in lowered:
            return True
    return False


def _build_messages(
    *,
    assistant: AiAssistant,
    user_message: str,
    retrieved_chunks: list[dict],
) -> list[dict]:
    """Assemble the ``messages`` payload for the LLM.

    Order matters:
      * system prompt (verbatim, no wrapping — Attacker C4 defence)
      * knowledge-base envelope (only when non-empty) as a
        ``role='user'`` message with ``name='knowledge_base'`` and a
        JSON body. Structured envelope, not string delimiters — the
        model sees data, not markup.
      * current user message.
    """
    messages: list[dict] = []
    if assistant.instructions:
        messages.append({"role": "system", "content": assistant.instructions})
    if retrieved_chunks:
        envelope = {
            "sources": [
                {"id": str(c["chunk_id"]), "text": c["text"]}
                for c in retrieved_chunks
                if float(c.get("score", 0)) >= _SIMILARITY_THRESHOLD
            ],
        }
        if envelope["sources"]:
            messages.append(
                {
                    "role": "user",
                    "name": "knowledge_base",
                    "content": json.dumps(envelope),
                }
            )
    messages.append({"role": "user", "content": user_message})
    return messages


class ChatRuntime:
    """Chat orchestrator. One instance per request/preview call.

    The runtime is stateful across the async generator lifetime:
    session, assistant, conversation, and message-meta id are all
    captured on ``self`` so a mid-stream disconnect check can find
    the meta row to update.
    """

    def __init__(
        self,
        *,
        db: AsyncSession,
        org_id: uuid.UUID,
        assistant_id: uuid.UUID,
        user_message: str,
        session_token: str,
        is_public: bool,
        is_disconnected: Callable[[], bool] | None = None,
    ) -> None:
        self._db = db
        self._org_id = org_id
        self._assistant_id = assistant_id
        self._user_message = user_message
        self._session_token = session_token
        self._is_public = is_public
        self._is_disconnected = is_disconnected or (lambda: False)

        self._assistant: AiAssistant | None = None
        self._conversation_id: uuid.UUID | None = None
        self._assistant_message_id: uuid.UUID | None = None
        self._retrieved_chunk_ids: list[uuid.UUID] = []

    # --- Guards ------------------------------------------------------

    async def _load_assistant(self) -> AiAssistant:
        row = await _da.get_assistant_by_id(self._db, self._assistant_id)
        if row is None:
            raise ValueError("assistant not found")
        self._assistant = row
        return row

    def _fallback_message(self) -> str:
        return (self._assistant.fallback_message if self._assistant else None) or (
            "I'm sorry, I can't help with that right now."
        )

    # --- Persistence -------------------------------------------------

    async def _create_conversation(self) -> uuid.UUID:
        """Preview + public both create a fresh conversation per
        call in v1. Persistence continuity (100-turn cap, session
        reuse across page loads) lands in Step 14 for public,
        Step 16 for the inbox surface."""
        external_id = f"{'preview' if not self._is_public else 'widget'}:{self._session_token}"
        cid = await _da.create_ai_widget_conversation(
            self._db,
            org_id=self._org_id,
            external_id=external_id,
        )
        self._conversation_id = cid
        return cid

    async def _persist_user_turn(self) -> None:
        assert self._conversation_id is not None
        await _da.insert_user_message(
            self._db,
            org_id=self._org_id,
            conversation_id=self._conversation_id,
            text_body=self._user_message,
        )

    async def _persist_assistant_reply_and_meta_pending(self, model: str) -> None:
        """Persist the empty assistant message row + the pending
        meta row so the outbox is initialised BEFORE the LLM call.
        The message text stays empty until the stream completes;
        the meta row captures the pending cost accounting."""
        assert self._conversation_id is not None
        assert self._assistant is not None
        msg_id = await _da.insert_assistant_message(
            self._db,
            org_id=self._org_id,
            conversation_id=self._conversation_id,
            text_body="",
        )
        await _da.insert_message_meta_pending(
            self._db,
            message_id=msg_id,
            org_id=self._org_id,
            assistant_id=self._assistant.id,
            model=model,
        )
        self._assistant_message_id = msg_id

    # --- Fallback yield ----------------------------------------------

    async def _yield_fallback_and_persist(
        self,
        reason: str,
    ) -> AsyncIterator[RuntimeChunk]:
        """Common tail for stop-keyword / budget-cap / retrieval-empty
        branches: persist the conversation + fallback text, then yield
        one token chunk + one error chunk + a done chunk. Callers
        commit before awaiting."""
        fallback = self._fallback_message()
        cid = await self._create_conversation()
        await self._persist_user_turn()
        await _da.insert_assistant_message(
            self._db,
            org_id=self._org_id,
            conversation_id=cid,
            text_body=fallback,
        )
        await self._db.commit()
        yield RuntimeChunk(type="token", delta=fallback)
        yield RuntimeChunk(type="error", reason=reason)
        yield RuntimeChunk(type="done", total_tokens=0, cost_usd=Decimal("0"))

    # --- Main entrypoint --------------------------------------------

    async def stream_reply(self) -> AsyncIterator[RuntimeChunk]:
        assistant = await self._load_assistant()

        # Draft assistants only accept preview traffic — a public
        # widget hitting a draft would leak the state to end-users.
        if self._is_public and assistant.status != AiAssistantStatus.active:
            async for chunk in self._yield_fallback_and_persist("assistant_not_active"):
                yield chunk
            return

        # 1. Stop-keyword short-circuit.
        if _matches_stop_keyword(self._user_message, list(assistant.stop_keywords or [])):
            async for chunk in self._yield_fallback_and_persist("stop_keyword_matched"):
                yield chunk
            return

        # 2. Budget-cap pre-flight (Attacker C5 defence).
        allowed, reason = await _budget_service.charge_budget(
            self._db,
            org_id=self._org_id,
            cost_usd=Decimal("0"),
            dry_run=True,
        )
        if not allowed:
            async for chunk in self._yield_fallback_and_persist(reason or "budget_cap_hit"):
                yield chunk
            return

        # 3. Persist the user turn + create conversation.
        await self._create_conversation()
        await self._persist_user_turn()

        # 4. Embed the user message for retrieval. If embed fails,
        # fall back to prompt-only (retrieval is best-effort — we
        # never let a knowledge-store hiccup block the assistant).
        llm = factory("openai", db=self._db, org_id=self._org_id, key_id=assistant.key_id)
        retrieved: list[dict] = []
        try:
            vectors = await llm.embed([self._user_message], model=_EMBED_MODEL)
            if vectors:
                retrieved = await _da.retrieve_chunks_for_assistant(
                    self._db,
                    org_id=self._org_id,
                    assistant_id=assistant.id,
                    query_embedding=vectors[0],
                    top_k=_TOP_K,
                )
        except ProviderError as exc:
            logger.warning(
                "ai_assistants.runtime embed_failed org=%s assistant=%s err=%s",
                self._org_id,
                assistant.id,
                exc,
            )

        self._retrieved_chunk_ids = [
            uuid.UUID(str(c["chunk_id"])) for c in retrieved
            if float(c.get("score", 0)) >= _SIMILARITY_THRESHOLD
        ]

        # 5. Build the messages payload (structured envelope for
        # retrieved chunks — no delimiter concatenation).
        messages = _build_messages(
            assistant=assistant,
            user_message=self._user_message,
            retrieved_chunks=retrieved,
        )

        # 6. Insert the outbox meta row + empty assistant message
        # BEFORE the LLM call. If the DB write fails after the
        # LLM succeeds (Absence #4), the reconcile job (Step 17)
        # picks up the orphaned pending row.
        await self._persist_assistant_reply_and_meta_pending(assistant.model)
        await self._db.commit()

        # 7. Stream from the provider. Accumulator captures the
        # complete reply for post-stream sanitiser + persistence.
        acc_parts: list[str] = []
        final_usage: Usage | None = None
        finish_reason: str | None = None
        chunks_since_disconnect_check = 0
        try:
            async for chunk in llm.stream(
                messages,
                model=assistant.model,
                temperature=float(assistant.temperature),
                max_tokens=_MAX_TOKENS_PER_REPLY,
            ):
                if isinstance(chunk, LLMChunk):
                    if chunk.delta:
                        acc_parts.append(chunk.delta)
                        yield RuntimeChunk(type="token", delta=chunk.delta)
                    if chunk.usage is not None:
                        final_usage = chunk.usage
                    if chunk.finish_reason is not None:
                        finish_reason = chunk.finish_reason
                chunks_since_disconnect_check += 1
                if chunks_since_disconnect_check >= _DISCONNECT_CHECK_EVERY_N_CHUNKS:
                    chunks_since_disconnect_check = 0
                    if self._is_disconnected():
                        # Client abandoned the stream — stop billing.
                        assert self._assistant_message_id is not None
                        await _da.update_message_meta_failed(
                            self._db,
                            message_id=self._assistant_message_id,
                            provider_error="client_disconnect",
                        )
                        await self._db.commit()
                        yield RuntimeChunk(type="error", reason="client_disconnect")
                        yield RuntimeChunk(
                            type="done",
                            total_tokens=(final_usage.total_tokens if final_usage else 0),
                            cost_usd=Decimal("0"),
                        )
                        return
        except ProviderError as exc:
            assert self._assistant_message_id is not None
            await _da.update_message_meta_failed(
                self._db,
                message_id=self._assistant_message_id,
                provider_error=str(exc),
            )
            await self._db.commit()
            fallback = self._fallback_message()
            yield RuntimeChunk(type="token", delta=fallback)
            yield RuntimeChunk(type="error", reason="provider_error")
            yield RuntimeChunk(type="done", total_tokens=0, cost_usd=Decimal("0"))
            return

        # 8. Compute cost server-side from the usage OpenAI returned
        # (never trust client-reported usage — Attacker M7).
        usage = final_usage or Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        cost = cost_for(usage, assistant.model)

        # 9. Assemble the final reply + optionally sanitise for
        # public embeds. Preview mode gets the raw reply so the
        # operator sees exactly what the model produced.
        full_reply = "".join(acc_parts)
        if self._is_public and assistant.output_sanitizer_enabled:
            full_reply = sanitize_output(full_reply, list(assistant.allowed_domains or []))

        # 10. Persist the sanitised reply text onto the assistant
        # message row + confirm the outbox row.
        assert self._assistant_message_id is not None
        assert self._conversation_id is not None
        from src.app.core.conversations.models import Message

        # Update the assistant-message row with the accumulated text.
        # Cross-module UPDATE — allowed because it's a plain write
        # into a single row we just inserted, and there's no
        # business rule on the conversations service that would
        # otherwise fire.
        from sqlalchemy import update as _update

        stmt = (
            _update(Message)
            .where(Message.id == self._assistant_message_id)
            .values(text=full_reply)
        )
        await self._db.execute(stmt)
        await _da.update_message_meta_confirmed(
            self._db,
            message_id=self._assistant_message_id,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=cost,
            retrieved_chunk_ids=self._retrieved_chunk_ids,
        )
        await self._db.commit()

        # 11. Charge the budget for the actual cost.
        await _budget_service.charge_budget(
            self._db,
            org_id=self._org_id,
            cost_usd=cost,
            dry_run=False,
        )

        yield RuntimeChunk(
            type="done",
            total_tokens=usage.total_tokens,
            cost_usd=cost,
        )
        _ = finish_reason  # captured for observability; not surfaced in v1.
        _ = datetime.now(UTC)  # keep import used


async def reply_once(
    *,
    db: AsyncSession,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    user_message: str,
    session_token: str,
    is_public: bool = False,
) -> str:
    """Non-streaming helper used by chatbot AI-nodes and any caller
    that just wants the final reply text. Runs the same pipeline as
    :meth:`ChatRuntime.stream_reply` and accumulates every ``token``
    chunk. Returns the fallback message when the runtime yields an
    ``error`` chunk.
    """
    runtime = ChatRuntime(
        db=db,
        org_id=org_id,
        assistant_id=assistant_id,
        user_message=user_message,
        session_token=session_token,
        is_public=is_public,
    )
    parts: list[str] = []
    async for chunk in runtime.stream_reply():
        if chunk.type == "token":
            parts.append(chunk.delta)
    return "".join(parts).strip()


__all__ = ["ChatRuntime", "RuntimeChunk", "reply_once"]
