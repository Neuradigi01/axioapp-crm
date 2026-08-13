"""Chatbot execution engine (``tasks/chatbot-builder`` Step 6).

State machine::

    start_run  ─→  running  ─→  process_step ─→  running  (advance)
                                              ─→  parked   (wait for event / delay)
                                              ─→  completed
                                              ─→  canceled (cap hit / bot archived /
                                                            human took over)
                                              ─→  errored  (handler raised)

    parked     ─→  resume_run (matcher or sweeper)  ─→  running

Node handlers register via :func:`register_node` in Steps 7-10. This
step ships the frame + a documented empty registry — an
unknown-node-type run cancels cleanly with reason
``unknown_node_type`` rather than crashing.

Runtime guards enforced here:

  * **Per-run step cap** — Decision §10 / Case #11. Runaway wait-loop
    protection: a run that hits ``_MAX_STEPS_PER_RUN`` nodes cancels
    with reason ``max_steps_exceeded``. Independent of the reply-cap
    meters, which are per-conversation-per-day.

  * **Per-conversation reply cap** — Decision §9 / Case #H2 hardening.
    Checked before dispatching send-capable nodes; on cap ends the
    run with reason ``conversation_reply_cap``.

  * **Per-org global reply cap** — Decision §9 hardening. Same shape;
    prevents billing blowout on a spam farm.

  * **WhatsApp 24h session window** — Decision §H3. Send-capable WA
    handlers call :func:`is_within_wa_window` themselves; the engine
    exposes the ``session_expired`` port as a first-class result so
    handlers can either fall back to a template send or take the
    labelled edge.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.chatbots import data_access as _dal
from src.app.core.chatbots.models import Chatbot, ChatbotRun

logger = logging.getLogger(__name__)


# --- Constants ------------------------------------------------------------


_MAX_STEPS_PER_RUN = 100

# Per-conversation reply cap (Decision §9). Configurable per-bot in
# a follow-up — v1 is a fixed default.
DEFAULT_CONVERSATION_REPLY_CAP = 50

# Per-org daily reply cap (Decision §H2 hardening). Fixed default
# for v1; a settings-page control lands with the sidebar UI.
DEFAULT_ORG_REPLY_CAP = 10_000

# Node types that produce an outbound message. Meter increments +
# WA 24h window checks gate these.
_SEND_CAPABLE_NODE_TYPES: frozenset[str] = frozenset(
    {
        "text_button",
        "media_button",
        "list",
        "template",
        "ask_question",
        "ask_address",
        "ask_location",
        "ask_media",
        "handoff_to_human",  # sends a final "handing off" line
        "single_ai_message",
    }
)


# --- Handler contract ----------------------------------------------------


@dataclass(slots=True)
class NodeResult:
    """Returned by every node handler. The engine reads this to
    advance the graph.

    * ``next_edge_label`` — pick the outbound edge by label. ``None``
      = "follow the only outbound edge", or terminate.
    * ``context_patch`` — merged into ``run.context`` before the
      next hop. Handlers put captured variables (``answers.*``,
      ``api.*``) here.
    * ``park_key`` — non-None marks the run parked. Shape:
      ``("reply", conversation_id)`` for wait-for-inbound;
      ``("delay", resume_at_iso)`` for scheduled resume. Sweeper +
      matcher use it to know how to resume.
    * ``skip_reason`` — non-None records the step as ``skipped``
      instead of ``completed``. Used by session-window /
      compliance / cap-hit gates.
    * ``end_run`` — handler explicitly requests the run to
      complete now (Handoff to Human sets this after firing the
      assignment).
    * ``error`` — non-None records the step ``errored`` and
      surfaces up as run.error.
    """

    next_edge_label: str | None = None
    context_patch: dict[str, Any] | None = None
    park_key: tuple[str, ...] | None = None
    skip_reason: str | None = None
    end_run: bool = False
    error: str | None = None
    output: dict[str, Any] = field(default_factory=dict)


NodeHandler = Callable[
    ["NodeExecutionContext"],
    Awaitable[NodeResult],
]


@dataclass(slots=True)
class NodeExecutionContext:
    """What each handler receives. Kept small — handlers pull the
    node config, run context (variables + answers), the session, and
    an ``is_test`` flag that gates real sends vs transcript-only
    output."""

    session: AsyncSession
    run: ChatbotRun
    bot: Chatbot
    node_id: str
    node_type: str
    node_config: dict[str, Any]
    run_context: dict[str, Any]
    is_test: bool = False
    dry_transcript: list[dict[str, Any]] | None = None


NODE_REGISTRY: dict[str, NodeHandler] = {}


def register_node(node_type: str, handler: NodeHandler) -> None:
    """Register a handler for a node type. Steps 7-10 call this at
    module import time; the sidebar canvas' node-type registry
    (Step 13) mirrors these keys."""
    NODE_REGISTRY[node_type] = handler


def resolve_handler(node_type: str) -> NodeHandler | None:
    return NODE_REGISTRY.get(node_type)


# --- Public API ----------------------------------------------------------


async def start_run(
    session: AsyncSession,
    *,
    bot: Chatbot,
    event: dict[str, Any],
    is_test: bool = False,
) -> ChatbotRun:
    """Create a run row for the winning bot and its triggering
    inbound event, then enqueue the first-node Celery hop.

    The row is committed here so the matcher's idempotency guard
    (Case #1) sees it on the next inbound. The first :func:`process_step`
    dispatch is a fire-and-forget ``.apply_async(...)`` — the
    Celery worker picks it up in its own session/context.

    ``is_test=True`` (from the test-fire endpoint) suppresses the
    Celery dispatch and returns the freshly-created run without
    running any nodes — the caller then dry-walks the graph.
    """
    conversation_id = _uuid_or_none(event.get("conversation_id"))
    contact_id = _uuid_or_none(event.get("contact_id"))
    message_id = _uuid_or_none(event.get("message_id"))

    first_node_id = _pick_entry_node_id(bot.graph or {})

    run = ChatbotRun(
        org_id=bot.org_id,
        chatbot_id=bot.id,
        chatbot_version=bot.version_number,
        conversation_id=conversation_id,
        contact_id=contact_id,
        lead_id=None,
        status="running" if first_node_id else "completed",
        current_node_id=first_node_id,
        context={
            "conversation_id": str(conversation_id) if conversation_id else None,
            "contact_id": str(contact_id) if contact_id else None,
            "last_inbound_message_id": str(message_id) if message_id else None,
            "last_inbound_text": event.get("text"),
            "channel": event.get("channel"),
            "is_first_message": bool(event.get("is_first_message")),
            "answers": {},
            "step_count": 0,
        },
        is_test=is_test,
    )
    if not first_node_id:
        run.completed_at = datetime.now(UTC)
    session.add(run)
    await session.flush()
    await session.commit()
    await session.refresh(run)

    logger.info(
        "chatbots.engine.run_started run=%s bot=%s conv=%s first_node=%s is_test=%s",
        run.id,
        bot.id,
        conversation_id,
        first_node_id,
        is_test,
    )

    if first_node_id and not is_test:
        _dispatch_process_step(run.id)

    return run


async def process_step(run_id: uuid.UUID) -> dict[str, Any]:
    """One engine hop. Called by :mod:`core.chatbots.tasks`. Opens
    its own session so the publisher / caller's transaction isn't
    held while the handler runs."""
    from src.app.shared.context import RequestContext, reset_context, set_context
    from src.app.shared.db import async_session

    async with async_session() as session:
        run = await _dal.get_run(session, run_id=run_id)
        if run is None:
            logger.warning("chatbots.engine.process_step_run_missing run=%s", run_id)
            return {"result": "run_missing"}

        token = set_context(RequestContext(org_id=run.org_id, user_id=None))
        try:
            return await _process_step_inner(session, run=run)
        finally:
            reset_context(token)


async def _process_step_inner(
    session: AsyncSession, *, run: ChatbotRun
) -> dict[str, Any]:
    if run.status not in ("running", "parked"):
        logger.info(
            "chatbots.engine.process_step_skipped run=%s status=%s",
            run.id,
            run.status,
        )
        return {"result": "not_active", "status": run.status}

    node_id = run.current_node_id
    if not node_id:
        # Nothing left to do → mark completed.
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        await session.commit()
        return {"result": "completed", "reason": "no_current_node"}

    # Bot load — chatbot_version pinned when the run started, so a
    # concurrent Save on the bot doesn't shift the graph out from
    # under an in-flight run. For v1 we load the current live bot;
    # the version-aware graph fetch is a follow-up.
    from sqlalchemy import select

    bot = (
        await session.execute(select(Chatbot).where(Chatbot.id == run.chatbot_id))
    ).scalar_one_or_none()
    if bot is None:
        await _cancel_run(session, run, reason="bot_deleted")
        return {"result": "canceled", "reason": "bot_deleted"}

    node = _find_node(bot.graph or {}, node_id)
    if node is None:
        await _cancel_run(session, run, reason="node_missing")
        return {"result": "canceled", "reason": "node_missing"}

    node_type = node.get("type") or ""
    node_config = node.get("config") or {}

    # Per-run step cap — cycle / runaway guard.
    step_count = int((run.context or {}).get("step_count") or 0)
    if step_count >= _MAX_STEPS_PER_RUN:
        await _cancel_run(session, run, reason="max_steps_exceeded")
        return {"result": "canceled", "reason": "max_steps_exceeded"}

    # Meter enforcement — only for send-capable node types.
    if node_type in _SEND_CAPABLE_NODE_TYPES and not run.is_test:
        per_conv = await _dal.increment_conversation_meter(
            session,
            org_id=run.org_id,
            bot_id=run.chatbot_id,
            conversation_id=run.conversation_id,
            cap=DEFAULT_CONVERSATION_REPLY_CAP,
        )
        if per_conv is None:
            _dal.insert_step_run(
                session,
                org_id=run.org_id,
                run_id=run.id,
                node_id=node_id,
                node_type=node_type,
                status="skipped",
                skip_reason="conversation_reply_cap",
            )
            await _cancel_run(session, run, reason="conversation_reply_cap")
            return {"result": "canceled", "reason": "conversation_reply_cap"}

        per_org = await _dal.increment_org_meter(
            session,
            org_id=run.org_id,
            cap=DEFAULT_ORG_REPLY_CAP,
        )
        if per_org is None:
            _dal.insert_step_run(
                session,
                org_id=run.org_id,
                run_id=run.id,
                node_id=node_id,
                node_type=node_type,
                status="skipped",
                skip_reason="org_reply_cap",
            )
            await _cancel_run(session, run, reason="org_reply_cap")
            return {"result": "canceled", "reason": "org_reply_cap"}

    # Dispatch to handler.
    handler = resolve_handler(node_type)
    if handler is None:
        # Steps 7-10 haven't registered a handler for this node type
        # yet. Cancel with a helpful reason so the operator sees it
        # in run history instead of a silent hang.
        _dal.insert_step_run(
            session,
            org_id=run.org_id,
            run_id=run.id,
            node_id=node_id,
            node_type=node_type,
            status="errored",
            error=f"no handler registered for node_type={node_type!r}",
        )
        await _cancel_run(session, run, reason="unknown_node_type")
        return {"result": "canceled", "reason": "unknown_node_type"}

    exec_context = NodeExecutionContext(
        session=session,
        run=run,
        bot=bot,
        node_id=node_id,
        node_type=node_type,
        node_config=node_config,
        run_context=run.context or {},
        is_test=run.is_test,
    )

    try:
        result = await handler(exec_context)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "chatbots.engine.handler_raised run=%s node=%s type=%s",
            run.id,
            node_id,
            node_type,
        )
        _dal.insert_step_run(
            session,
            org_id=run.org_id,
            run_id=run.id,
            node_id=node_id,
            node_type=node_type,
            status="errored",
            error=str(exc),
        )
        await _mark_errored(session, run, error=str(exc))
        return {"result": "errored", "reason": str(exc)}

    # Persist step_run audit row for this hop.
    _dal.insert_step_run(
        session,
        org_id=run.org_id,
        run_id=run.id,
        node_id=node_id,
        node_type=node_type,
        status=("skipped" if result.skip_reason else "completed"),
        output=result.output,
        output_edge_label=result.next_edge_label,
        skip_reason=result.skip_reason,
    )

    # Merge context_patch into run.context (immutable-style copy so
    # SQLAlchemy sees the change).
    if result.context_patch:
        new_ctx = dict(run.context or {})
        new_ctx.update(result.context_patch)
        run.context = new_ctx

    # Advance step counter.
    ctx = dict(run.context or {})
    ctx["step_count"] = step_count + 1
    run.context = ctx

    # Park path: mark parked + persist + return; sweeper / matcher
    # will resume when the wait key fires.
    if result.park_key is not None:
        run.status = "parked"
        park_ctx = dict(run.context or {})
        park_ctx["park_key"] = list(result.park_key)
        run.context = park_ctx
        await session.commit()
        logger.info(
            "chatbots.engine.parked run=%s node=%s key=%s",
            run.id,
            node_id,
            result.park_key,
        )
        return {"result": "parked", "park_key": list(result.park_key)}

    # End-run path: handler explicitly finished.
    if result.end_run:
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        await session.commit()
        logger.info("chatbots.engine.ended_by_handler run=%s node=%s", run.id, node_id)
        return {"result": "completed", "reason": "handler_end_run"}

    # Advance to next node via edge label.
    next_node_id = _find_next_node(bot.graph or {}, node_id, result.next_edge_label)
    if next_node_id is None:
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        await session.commit()
        logger.info("chatbots.engine.completed_no_next run=%s", run.id)
        return {"result": "completed", "reason": "no_next_edge"}

    run.current_node_id = next_node_id
    run.status = "running"
    await session.commit()

    # Enqueue next hop — recursion via Celery, never inline.
    if not run.is_test:
        _dispatch_process_step(run.id)

    return {"result": "advanced", "next_node_id": next_node_id}


async def resume_run(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    resume_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wake a parked run: update ``last_inbound_*`` in context, flip
    status to ``running``, enqueue the next :func:`process_step`.
    Called by the trigger matcher when idempotency guard fires
    (Case #1) and by :func:`sweep_delay_resumes` for delay-parked
    runs.
    """
    run = await _dal.get_run(session, run_id=run_id)
    if run is None:
        return {"result": "run_missing"}
    if run.status != "parked":
        return {"result": "not_parked", "status": run.status}

    ctx = dict(run.context or {})
    resumed_by = "inbound"
    if resume_event:
        if "text" in resume_event:
            ctx["last_inbound_text"] = resume_event.get("text")
        if "message_id" in resume_event:
            ctx["last_inbound_message_id"] = resume_event.get("message_id")
        # Sweeper stamps ``_resumed_by`` to distinguish timeout /
        # delay_expired from inbound. Matcher-driven resumes omit
        # the key (default 'inbound').
        resumed_by = str(resume_event.get("_resumed_by") or "inbound")
    # Drop the park key so a stale resume doesn't loop.
    ctx.pop("park_key", None)
    # Also clear next_step_at — the sweeper picks parked rows by
    # this column, so leaving it set would cause a re-sweep next
    # tick and an infinite resume loop.
    run.next_step_at = None
    # Flag the resume so node handlers (text_button, list, ask_*,
    # delay) know to interpret last_inbound_* / resumed_by
    # correctly. Handlers clear these before advancing.
    ctx["resumed_from_park"] = True
    ctx["resumed_by"] = resumed_by
    run.context = ctx

    run.status = "running"
    await session.commit()

    if not run.is_test:
        _dispatch_process_step(run.id)

    return {"result": "resumed"}


async def cancel_parked_runs_for_conversation(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    reason: str,
) -> int:
    """Cancel every parked run on the given conversation. Used by
    the human-takeover hook in ``conversations.service.send_outbound``
    (Case #10). Returns the count canceled."""
    runs = await _dal.list_parked_runs_for_conversation(
        session, conversation_id=conversation_id
    )
    for run in runs:
        run.status = "canceled"
        run.canceled_reason = reason
        run.completed_at = datetime.now(UTC)
    if runs:
        await session.commit()
    return len(runs)


# --- Internal helpers ----------------------------------------------------


async def _cancel_run(
    session: AsyncSession, run: ChatbotRun, *, reason: str
) -> None:
    run.status = "canceled"
    run.canceled_reason = reason
    run.completed_at = datetime.now(UTC)
    await session.commit()
    logger.info("chatbots.engine.canceled run=%s reason=%s", run.id, reason)


async def _mark_errored(
    session: AsyncSession, run: ChatbotRun, *, error: str
) -> None:
    run.status = "errored"
    run.error = error
    run.completed_at = datetime.now(UTC)
    await session.commit()


def _pick_entry_node_id(graph: dict[str, Any]) -> str | None:
    """Return the id of the entry node — the node with in-degree 0.
    If multiple such nodes exist, picks the first in the ``nodes``
    array (canvas save order). ``None`` on empty graph."""
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not nodes:
        return None
    targets = {e.get("target") for e in edges if e.get("target")}
    for node in nodes:
        node_id = node.get("id")
        if node_id and node_id not in targets:
            return node_id
    # Fallback — every node is a target (fully-connected cycle;
    # graph.py should have rejected this at save-time). Pick the
    # first node so we don't crash.
    first = nodes[0]
    return first.get("id")


def _find_node(graph: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    for node in graph.get("nodes") or []:
        if node.get("id") == node_id:
            return node
    return None


def _find_next_node(
    graph: dict[str, Any],
    source_id: str,
    edge_label: str | None,
) -> str | None:
    """Follow the outbound edge matching ``edge_label``. If
    ``edge_label`` is None, follow the first (or only) unlabeled
    outbound edge; if none exists, follow any outbound edge."""
    edges = graph.get("edges") or []
    outbound = [e for e in edges if e.get("source") == source_id]
    if not outbound:
        return None

    if edge_label is not None:
        for e in outbound:
            if e.get("label") == edge_label:
                return e.get("target")
        # Labeled edge requested but no match → nothing to do.
        return None

    for e in outbound:
        if e.get("label") is None:
            return e.get("target")
    return outbound[0].get("target")


def _dispatch_process_step(run_id: uuid.UUID) -> None:
    """Deferred Celery import so the engine stays importable in dev
    shells without Celery installed. The tasks module's ``_Stub``
    fallback keeps ``apply_async`` a no-op there."""
    from src.app.core.chatbots import tasks as chatbot_tasks

    try:
        chatbot_tasks.process_step.apply_async(args=(str(run_id),))
    except Exception:  # noqa: BLE001
        logger.exception("chatbots.engine.dispatch_failed run=%s", run_id)


def _uuid_or_none(raw: Any) -> uuid.UUID | None:
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None
