"""Data-access for the AI Assistants module.

Pure CRUD. No transactions, no permission checks, no business
logic — those live in :mod:`~core.ai_assistants.service`.

Two helpers land here at Step 5 for the BYOK reassign wiring
(``count_assistants_by_key_id`` + ``reassign_assistant_key_ids``);
Step 6 adds the full CRUD used by the operator router
(``list_assistants`` / ``get_assistant_by_id`` /
``get_assistant_by_id_no_org_filter`` / ``insert_assistant`` /
``delete_assistant`` / ``insert_instruction_audit`` +
``get_provider_key_by_id``). Optimistic-concurrency UPDATE goes
through SQLAlchemy's ``version_id_col`` machinery on ``AiAssistant``
— the service just sets ``instance.version = payload.version``
before mutating fields, and SQLAlchemy raises ``StaleDataError``
when the DB row moved on.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.ai_assistants.models import (
    AiAssistant,
    AiAssistantInstructionAudit,
    AiAssistantKnowledge,
    AiAssistantStatus,
    KnowledgeSourceType,
    KnowledgeStatus,
)
from src.app.core.integrations.ai.models import AiProviderKey

# --- Read helpers --------------------------------------------------------


async def get_assistant_by_id(
    db: AsyncSession,
    assistant_id: uuid.UUID,
) -> AiAssistant | None:
    """RLS + TenantScoped filter ensure this only returns rows
    belonging to the caller's org. Step 6's service uses this for
    reads AFTER the timing-safe 404 pre-check has fired."""
    stmt = select(AiAssistant).where(AiAssistant.id == assistant_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_assistant_row_no_org_filter(
    db: AsyncSession,
    assistant_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Raw-SQL lookup that bypasses the TenantScoped auto-filter so
    the timing-safe 404 path always issues a DB hit whether the row
    exists in another org or nowhere at all.

    Returns ``(id, org_id)`` on hit; ``None`` on miss. The service
    compares ``org_id`` against the caller's org and 404s uniformly
    on either branch.
    """
    result = await db.execute(
        text("SELECT id, org_id FROM tbl_ai_assistants WHERE id = :id LIMIT 1"),
        {"id": str(assistant_id)},
    )
    row = result.first()
    if row is None:
        return None
    return uuid.UUID(str(row[0])), uuid.UUID(str(row[1]))


async def find_active_assistant_bound_to_channel(
    db: AsyncSession,
    *,
    channel: str,
    exclude_assistant_id: uuid.UUID | None = None,
) -> AiAssistant | None:
    """Return the active assistant in the caller's org whose
    ``bound_channels`` array contains ``channel``, or ``None``.

    Used by the service's channel-conflict pre-flight (Step 1) and by
    the inbound dispatch (Step 5). ``exclude_assistant_id`` lets the
    conflict check skip the row being edited so re-saving without
    changing channels doesn't self-conflict. TenantScoped RLS filter
    keeps the query org-scoped."""
    stmt = select(AiAssistant).where(
        AiAssistant.status == AiAssistantStatus.active,
        # JSONB ``?`` operator: element-exists in top-level array.
        # Uses the GIN index created in migration 0209.
        AiAssistant.bound_channels.op("?")(channel),
    )
    if exclude_assistant_id is not None:
        stmt = stmt.where(AiAssistant.id != exclude_assistant_id)
    stmt = stmt.limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_active_bound_channels(db: AsyncSession) -> set[str]:
    """Return the union of ``bound_channels`` across every active
    assistant in the caller's org (TenantScoped auto-filter narrows
    the query). Used by the conversations router to compute the
    per-row ``ai_active`` flag without an N+1 per conversation:
    fetch this set once, then check membership in memory.

    Returns an empty set when the org has no active assistants."""
    stmt = select(AiAssistant.bound_channels).where(
        AiAssistant.status == AiAssistantStatus.active,
    )
    result = await db.execute(stmt)
    channels: set[str] = set()
    for (row_channels,) in result.all():
        if row_channels:
            channels.update(str(c) for c in row_channels)
    return channels


async def list_assistants(
    db: AsyncSession,
    *,
    filter_status: AiAssistantStatus | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AiAssistant]:
    """Paginated list scoped by the TenantScoped auto-filter to the
    caller's org. Ordered by ``updated_at DESC`` so the most-recently
    edited assistant surfaces first."""
    stmt = select(AiAssistant)
    if filter_status is not None:
        stmt = stmt.where(AiAssistant.status == filter_status)
    if search:
        stmt = stmt.where(AiAssistant.name.ilike(f"%{search}%"))
    stmt = stmt.order_by(AiAssistant.updated_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_assistants(
    db: AsyncSession,
    *,
    filter_status: AiAssistantStatus | None = None,
    search: str | None = None,
) -> int:
    stmt = select(func.count()).select_from(AiAssistant)
    if filter_status is not None:
        stmt = stmt.where(AiAssistant.status == filter_status)
    if search:
        stmt = stmt.where(AiAssistant.name.ilike(f"%{search}%"))
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def get_provider_key_by_id(
    db: AsyncSession,
    key_id: uuid.UUID,
) -> AiProviderKey | None:
    """Cross-org guard input. TenantScoped auto-filter narrows the
    result to keys belonging to the caller's org — service treats a
    None result as 404 (never leaks whether the key exists in
    another org)."""
    stmt = select(AiProviderKey).where(AiProviderKey.id == key_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# --- Write helpers -------------------------------------------------------


async def insert_assistant(
    db: AsyncSession,
    **values: Any,
) -> AiAssistant:
    """Stage an INSERT of :class:`AiAssistant`. Service commits."""
    row = AiAssistant(**values)
    db.add(row)
    return row


async def delete_assistant(
    db: AsyncSession,
    assistant_id: uuid.UUID,
) -> None:
    """Hard-delete. FK cascades to knowledge + chunks + audit rows;
    message_meta.assistant_id SET NULL to preserve cost history.
    Service already verified the row belongs to the caller's org."""
    row = await get_assistant_by_id(db, assistant_id)
    if row is not None:
        await db.delete(row)


async def insert_instruction_audit(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    field_name: str,
    old_value: str | None,
    new_value: str | None,
) -> AiAssistantInstructionAudit:
    row = AiAssistantInstructionAudit(
        org_id=org_id,
        assistant_id=assistant_id,
        changed_by_user_id=user_id,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
    )
    db.add(row)
    return row


async def set_assistant_status(
    db: AsyncSession,
    *,
    assistant_id: uuid.UUID,
    status: AiAssistantStatus,
) -> None:
    """Update ``status`` only. Used by the archive endpoint —
    goes through raw UPDATE so we don't collide with the
    ``version_id_col`` on the model (archive isn't user-edit).
    """
    stmt = update(AiAssistant).where(AiAssistant.id == assistant_id).values(status=status)
    await db.execute(stmt)


# --- Step-5 cross-module helpers (unchanged) -----------------------------


async def count_assistants_by_key_id(
    db: AsyncSession,
    key_id: uuid.UUID,
) -> int:
    """Number of assistants (any status) that reference this
    provider key. TenantScoped auto-filter scopes by caller's org."""
    stmt = select(func.count()).select_from(AiAssistant).where(AiAssistant.key_id == key_id)
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def reassign_assistant_key_ids(
    db: AsyncSession,
    *,
    from_key_id: uuid.UUID,
    to_key_id: uuid.UUID,
) -> int:
    """Bulk UPDATE of every assistant's ``key_id`` from one key to
    another. TenantScoped auto-filter narrows to caller's org."""
    stmt = update(AiAssistant).where(AiAssistant.key_id == from_key_id).values(key_id=to_key_id)
    result = await db.execute(stmt)
    return int(result.rowcount or 0)


# --- Runtime helpers (Step 9) -------------------------------------------


async def retrieve_chunks_for_assistant(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """HNSW top-K retrieval scoped to a single assistant's knowledge.

    Joins ``tbl_ai_assistant_chunks`` with ``tbl_ai_assistant_knowledge``
    so only chunks whose parent knowledge row has ``status='ready'``
    are returned (mid-ingest chunks are never retrieved). Additional
    filter on ``chunks.status='ready'`` guards against Step 10's
    soft-delete path.

    Sets the RLS session variable first so the tenant-isolation
    policy fires; belt+braces with the explicit ``WHERE org_id`` in
    the query.
    """
    await db.execute(
        text("SELECT set_config('app.current_org_id', :o, true)"),
        {"o": str(org_id)},
    )
    vec_literal = "[" + ",".join(f"{float(x):.7f}" for x in query_embedding) + "]"
    stmt = text(
        """
        SELECT c.id AS chunk_id,
               c.text,
               c.token_count,
               c.knowledge_id,
               1 - (c.embedding <=> (:q)::vector) AS score
        FROM tbl_ai_assistant_chunks c
        JOIN tbl_ai_assistant_knowledge k ON c.knowledge_id = k.id
        WHERE c.org_id = :org_id
          AND k.assistant_id = :assistant_id
          AND c.status = 'ready'
          AND k.status = 'ready'
        ORDER BY c.embedding <=> (:q)::vector
        LIMIT :k
        """
    )
    result = await db.execute(
        stmt,
        {
            "org_id": str(org_id),
            "assistant_id": str(assistant_id),
            "q": vec_literal,
            "k": int(top_k),
        },
    )
    return [dict(r) for r in result.mappings().all()]


async def create_ai_widget_conversation(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    external_id: str,
) -> uuid.UUID:
    """INSERT a fresh conversation with ``channel='ai_widget'``.
    Returns the new conversation id. Caller commits."""
    from src.app.core.conversations.models import Conversation, ConversationChannel

    conv = Conversation(
        org_id=org_id,
        channel=ConversationChannel.ai_widget,
        external_id=external_id,
    )
    db.add(conv)
    await db.flush()
    return conv.id


async def insert_user_message(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    conversation_id: uuid.UUID,
    text_body: str,
) -> uuid.UUID:
    """INSERT the inbound (user-typed) message. Returns its id."""
    from src.app.core.conversations.models import Message, MessageDirection

    msg = Message(
        org_id=org_id,
        conversation_id=conversation_id,
        direction=MessageDirection.in_,
        text=text_body,
    )
    db.add(msg)
    await db.flush()
    return msg.id


async def insert_assistant_message(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    conversation_id: uuid.UUID,
    text_body: str,
) -> uuid.UUID:
    """INSERT the outbound (assistant-generated) message. Returns id."""
    from src.app.core.conversations.models import Message, MessageDirection

    msg = Message(
        org_id=org_id,
        conversation_id=conversation_id,
        direction=MessageDirection.out,
        text=text_body,
    )
    db.add(msg)
    await db.flush()
    return msg.id


async def insert_message_meta_pending(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    model: str,
) -> None:
    """Outbox INSERT — ``cost_status='pending_llm_confirm'`` pre-LLM-call.
    Step 17's reconcile job catches rows still pending > 5 min."""
    from src.app.core.ai_assistants.models import AiAssistantMessageMeta, CostStatus

    row = AiAssistantMessageMeta(
        message_id=message_id,
        org_id=org_id,
        assistant_id=assistant_id,
        model=model,
        cost_status=CostStatus.pending_llm_confirm,
    )
    db.add(row)
    await db.flush()


async def update_message_meta_confirmed(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cost_usd: Any,
    retrieved_chunk_ids: list[uuid.UUID],
) -> None:
    from src.app.core.ai_assistants.models import AiAssistantMessageMeta, CostStatus

    stmt = (
        update(AiAssistantMessageMeta)
        .where(AiAssistantMessageMeta.message_id == message_id)
        .values(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            cost_status=CostStatus.confirmed,
            retrieved_chunk_ids=retrieved_chunk_ids,
        )
    )
    await db.execute(stmt)


async def update_message_meta_failed(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    provider_error: str,
) -> None:
    from src.app.core.ai_assistants.models import AiAssistantMessageMeta, CostStatus

    stmt = (
        update(AiAssistantMessageMeta)
        .where(AiAssistantMessageMeta.message_id == message_id)
        .values(
            cost_status=CostStatus.failed,
            provider_error=provider_error,
        )
    )
    await db.execute(stmt)


# --- Knowledge helpers (Step 10) -----------------------------------------


async def insert_knowledge(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    source_type: KnowledgeSourceType,
    content_hash: bytes,
    original_filename: str | None = None,
    body_text: str | None = None,
    url: str | None = None,
    mime_type: str | None = None,
    size_bytes: int | None = None,
) -> AiAssistantKnowledge:
    """Stage a new knowledge row in ``status='pending'``. The service
    layer follows with ``db.flush()`` to surface unique-index
    violations (dedup returns the pre-existing row), then commits +
    dispatches the Celery ingest task."""
    row = AiAssistantKnowledge(
        org_id=org_id,
        assistant_id=assistant_id,
        source_type=source_type,
        content_hash=content_hash,
        original_filename=original_filename,
        body_text=body_text,
        url=url,
        mime_type=mime_type,
        size_bytes=size_bytes,
        status=KnowledgeStatus.pending,
    )
    db.add(row)
    return row


async def get_knowledge_by_id(
    db: AsyncSession,
    knowledge_id: uuid.UUID,
) -> AiAssistantKnowledge | None:
    """RLS + TenantScoped filter — only returns rows in the caller's
    org. Used by the operator router. Ingest task uses the
    ``_no_org_filter`` variant because it runs without a request
    context."""
    stmt = select(AiAssistantKnowledge).where(AiAssistantKnowledge.id == knowledge_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_knowledge_by_id_no_org_filter(
    db: AsyncSession,
    knowledge_id: uuid.UUID,
) -> AiAssistantKnowledge | None:
    """Bypass TenantScoped — used by the Celery ingest task which
    runs without a request context. RLS still fires because the
    ingest sets ``app.current_org_id`` before this call."""
    result = await db.execute(
        text(
            """
            SELECT id, org_id, assistant_id, source_type, original_filename,
                   body_text, url, content_hash, mime_type, size_bytes,
                   status, status_message, progress_pct, heartbeat_at,
                   chunk_count, created_at, updated_at
            FROM tbl_ai_assistant_knowledge
            WHERE id = :id
            LIMIT 1
            """
        ),
        {"id": str(knowledge_id)},
    )
    row = result.first()
    if row is None:
        return None
    # Hydrate as an ORM object so callers can access fields via
    # attribute lookups. We build the ORM instance directly (no
    # merge) — the mapper won't identity-map it, which is what we
    # want inside a fresh task session.
    return AiAssistantKnowledge(
        id=row.id,
        org_id=row.org_id,
        assistant_id=row.assistant_id,
        source_type=KnowledgeSourceType(row.source_type),
        original_filename=row.original_filename,
        body_text=row.body_text,
        url=row.url,
        content_hash=bytes(row.content_hash),
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        status=KnowledgeStatus(row.status),
        status_message=row.status_message,
        progress_pct=row.progress_pct,
        heartbeat_at=row.heartbeat_at,
        chunk_count=row.chunk_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def get_knowledge_by_hash(
    db: AsyncSession,
    *,
    assistant_id: uuid.UUID,
    content_hash: bytes,
) -> AiAssistantKnowledge | None:
    """Look up by ``(assistant_id, content_hash)`` — the unique
    constraint dedups here. Returns the existing row so the router
    can return it verbatim instead of double-ingesting."""
    stmt = (
        select(AiAssistantKnowledge)
        .where(AiAssistantKnowledge.assistant_id == assistant_id)
        .where(AiAssistantKnowledge.content_hash == content_hash)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_knowledge_by_assistant(
    db: AsyncSession,
    *,
    assistant_id: uuid.UUID,
) -> list[AiAssistantKnowledge]:
    """Ordered by ``created_at DESC`` so newest uploads render first
    in the operator UI."""
    stmt = (
        select(AiAssistantKnowledge)
        .where(AiAssistantKnowledge.assistant_id == assistant_id)
        .order_by(AiAssistantKnowledge.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def set_status(
    db: AsyncSession,
    *,
    knowledge_id: uuid.UUID,
    status: KnowledgeStatus,
    message: str | None = None,
    chunk_count: int | None = None,
    progress_pct: int | None = None,
    clear_heartbeat: bool = False,
) -> None:
    """Bulk-update helper used by the ingest task's status
    transitions. Only touches the columns the caller asked for."""
    values: dict[str, Any] = {
        "status": status,
        "status_message": message,
    }
    if chunk_count is not None:
        values["chunk_count"] = chunk_count
    if progress_pct is not None:
        values["progress_pct"] = progress_pct
    if clear_heartbeat:
        values["heartbeat_at"] = None
    stmt = (
        update(AiAssistantKnowledge).where(AiAssistantKnowledge.id == knowledge_id).values(**values)
    )
    await db.execute(stmt)


async def heartbeat_pulse(
    db: AsyncSession,
    *,
    knowledge_id: uuid.UUID,
    progress_pct: int | None = None,
) -> None:
    """Bump ``heartbeat_at=now()`` + optionally ``progress_pct``.
    Called by the ingest task at least every 30s so the Step 17
    stuck-ingest reaper can tell "in-flight" from "worker crashed"."""
    values: dict[str, Any] = {"heartbeat_at": func.now()}
    if progress_pct is not None:
        values["progress_pct"] = progress_pct
    stmt = (
        update(AiAssistantKnowledge).where(AiAssistantKnowledge.id == knowledge_id).values(**values)
    )
    await db.execute(stmt)


async def delete_knowledge_row(
    db: AsyncSession,
    knowledge_id: uuid.UUID,
) -> None:
    """Hard-delete the knowledge row. FK CASCADE removes chunks."""
    stmt = select(AiAssistantKnowledge).where(AiAssistantKnowledge.id == knowledge_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        await db.delete(row)


# --- Styling-config helpers (Step 13) -----------------------------------


async def set_assistant_styling_key(
    db: AsyncSession,
    *,
    assistant_id: uuid.UUID,
    key: str,
    value: Any,
) -> None:
    """Merge one key into ``styling_config`` JSONB in-place — Postgres
    ``jsonb_set`` so we don't clobber sibling keys and don't need to
    round-trip the whole blob through the ORM. Bypasses OCC on
    purpose: profile-picture URL is an out-of-band asset the operator
    might upload while the editor is dirty on other fields.
    """
    stmt = text(
        """
        UPDATE tbl_ai_assistants
        SET styling_config = jsonb_set(
            COALESCE(styling_config, '{}'::jsonb),
            ARRAY[:key],
            to_jsonb(cast(:value AS text)),
            true
        )
        WHERE id = :id
        """
    )
    await db.execute(
        stmt,
        {"id": str(assistant_id), "key": key, "value": str(value)},
    )


async def unset_assistant_styling_key(
    db: AsyncSession,
    *,
    assistant_id: uuid.UUID,
    key: str,
) -> None:
    """Delete one key from ``styling_config`` (JSONB `-` operator).
    Idempotent — deleting a missing key is a no-op."""
    stmt = text(
        """
        UPDATE tbl_ai_assistants
        SET styling_config = COALESCE(styling_config, '{}'::jsonb) - :key
        WHERE id = :id
        """
    )
    await db.execute(stmt, {"id": str(assistant_id), "key": key})


# --- Analytics (Step 16) --------------------------------------------------


async def analytics_message_and_cost(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    window_days: int,
) -> tuple[int, str]:
    """SUM + COUNT over ``tbl_ai_assistant_message_meta`` filtered by
    ``(org_id, assistant_id, created_at > now() - :window)``. Returns
    ``(message_count, total_cost_usd_str)`` so callers can decide
    whether to render "$0.00" or "no data yet"."""
    stmt = text(
        """
        SELECT COUNT(*)                     AS n,
               COALESCE(SUM(cost_usd), 0)   AS total
        FROM tbl_ai_assistant_message_meta
        WHERE org_id = :org_id
          AND assistant_id = :assistant_id
          AND created_at > now() - make_interval(days => :window)
        """
    )
    result = await db.execute(
        stmt,
        {
            "org_id": str(org_id),
            "assistant_id": str(assistant_id),
            "window": int(window_days),
        },
    )
    row = result.first()
    if row is None:
        return 0, "0"
    return int(row.n or 0), str(row.total or 0)


async def analytics_top_questions(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    window_days: int,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Top ``limit`` normalised inbound messages (``LOWER(TRIM(text))``)
    across conversations that had at least one AI-generated reply for
    this assistant.

    The join is: message_meta -> messages (assistant replies)
    -> conversation_id -> user messages on the same conversation.
    We deliberately DON'T rely on ``tbl_conversations.metadata`` (no
    such column exists) — instead the message_meta table is the
    authoritative ``(assistant_id, message_id)`` link so joining
    through it stays index-supported.
    """
    stmt = text(
        """
        WITH assistant_convs AS (
          SELECT DISTINCT m_asst.conversation_id
          FROM tbl_ai_assistant_message_meta mm
          JOIN tbl_messages m_asst ON m_asst.id = mm.message_id
          WHERE mm.org_id = :org_id
            AND mm.assistant_id = :assistant_id
            AND mm.created_at > now() - make_interval(days => :window)
        )
        SELECT LOWER(TRIM(m.text)) AS normalized,
               COUNT(*)            AS n
        FROM tbl_messages m
        JOIN assistant_convs ac ON ac.conversation_id = m.conversation_id
        WHERE m.direction = 'in'
          AND m.text IS NOT NULL
          AND length(trim(m.text)) > 0
          AND m.created_at > now() - make_interval(days => :window)
        GROUP BY LOWER(TRIM(m.text))
        ORDER BY COUNT(*) DESC, LOWER(TRIM(m.text)) ASC
        LIMIT :limit
        """
    )
    result = await db.execute(
        stmt,
        {
            "org_id": str(org_id),
            "assistant_id": str(assistant_id),
            "window": int(window_days),
            "limit": int(limit),
        },
    )
    return [{"normalized": str(r.normalized), "count": int(r.n)} for r in result.all()]


__all__ = [
    "analytics_message_and_cost",
    "analytics_top_questions",
    "count_assistants",
    "count_assistants_by_key_id",
    "create_ai_widget_conversation",
    "delete_assistant",
    "delete_knowledge_row",
    "find_active_assistant_bound_to_channel",
    "get_assistant_by_id",
    "get_assistant_row_no_org_filter",
    "get_knowledge_by_hash",
    "get_knowledge_by_id",
    "get_knowledge_by_id_no_org_filter",
    "get_provider_key_by_id",
    "heartbeat_pulse",
    "insert_assistant",
    "insert_assistant_message",
    "insert_instruction_audit",
    "insert_knowledge",
    "insert_message_meta_pending",
    "insert_user_message",
    "list_active_bound_channels",
    "list_assistants",
    "list_knowledge_by_assistant",
    "reassign_assistant_key_ids",
    "retrieve_chunks_for_assistant",
    "set_assistant_status",
    "set_assistant_styling_key",
    "set_status",
    "unset_assistant_styling_key",
    "update_message_meta_confirmed",
    "update_message_meta_failed",
]
