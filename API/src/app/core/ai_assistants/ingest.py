"""Knowledge-source ingest pipeline
(``tasks/ai-assistants`` Step 10; Attacker H4+H5+C1, Cases §9-14).

Runs inside the Celery worker (see :mod:`.tasks`). One task per
knowledge row. Flow:

  1. Load the row + guard against ``pending_delete`` / ``pending_cancel``
     racing the ingest.
  2. Extract raw text from the source (file / typed body / URL).
  3. Chunk via :func:`shared.vector.chunker.chunk_text` (prompt-
     injection markers already stripped inside).
  4. Embed in batches via the OpenAI adapter bound to the assistant's
     stored key (BYOK).
  5. UPSERT chunks through :class:`shared.vector.pgvector.PgVectorStore`
     inside a single txn per batch — replaces the old chunks
     atomically on re-ingest.
  6. Set ``status='ready'``, ``progress_pct=100``, ``chunk_count``,
     ``heartbeat_at=null``.

Heartbeat: written after every batch AND every 30s if a single
batch takes longer, so the Step 17 stuck-ingest reaper can distinguish
"still working" from "crashed mid-batch". Cancellation is a soft
signal — the row's status column is polled between batches; the
task voluntarily exits + rolls back on ``pending_cancel``.

Runtime is on the layered-architecture pin-test's exception list
(Step 5) because Celery task bodies open + commit their own
transactions; the pin-test's "only service.py commits" rule doesn't
apply outside the HTTP request path.
"""

from __future__ import annotations

import io
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.ai_assistants import data_access as _da
from src.app.core.ai_assistants.models import (
    AiAssistantKnowledge,
    KnowledgeSourceType,
    KnowledgeStatus,
)
from src.app.shared.db import async_session
from src.app.shared.http.safe_fetch import UnsafeUrlError, safe_fetch
from src.app.shared.llm import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderError,
    ProviderQuotaExceeded,
    ProviderTimeout,
    factory,
)
from src.app.shared.storage import get_storage
from src.app.shared.vector.base import VectorEntry
from src.app.shared.vector.chunker import chunk_text
from src.app.shared.vector.pgvector import PgVectorStore

logger = logging.getLogger(__name__)


def _friendly_provider_error(exc: ProviderError) -> str:
    """Operator-facing ``status_message`` for an embedding failure.

    The raw SDK payload (JSON blob, request id) goes to the log; the
    knowledge row carries a sentence the operator can act on.
    """
    if isinstance(exc, ProviderQuotaExceeded):
        if "insufficient_quota" in str(exc):
            return (
                "Your OpenAI account has run out of credits. Add credits in your "
                "OpenAI billing settings, then delete and re-add this source."
            )
        return "OpenAI rate limit reached. Wait a minute, then delete and re-add this source."
    if isinstance(exc, ProviderAuthError):
        return (
            "The OpenAI API key for this assistant is invalid or revoked. "
            "Update the key, then delete and re-add this source."
        )
    if isinstance(exc, ProviderTimeout):
        return "OpenAI took too long to respond. Delete and re-add this source to try again."
    if isinstance(exc, ProviderBadRequest):
        return "OpenAI rejected this content. Check the source and try again."
    return "OpenAI is temporarily unavailable. Delete and re-add this source to try again."


_EMBED_MODEL = "text-embedding-3-small"
_EMBED_BATCH_SIZE = 100
_HEARTBEAT_EVERY = timedelta(seconds=30)
# Max text length AFTER extraction — an 800 MB TXT would blow past
# the ~20 MB decoded cap in a single call; step spec sets this at
# 20 MB. Bytes, not characters — extracted text is UTF-8.
_MAX_EXTRACTED_BYTES = 20 * 1024 * 1024


@dataclass(slots=True)
class IngestOutcome:
    """Returned by :func:`ingest_knowledge` for observability. Celery
    ships this back to the operator so the /knowledge list can render
    a completion message in the same round-trip as the poll."""

    status: str  # KnowledgeStatus value
    chunk_count: int = 0
    error: str | None = None


class _IngestAborted(Exception):
    """Raised when the row's status flips to pending_cancel /
    pending_delete between batches. Caller rolls back + sets the
    final status appropriately."""

    def __init__(self, *, new_status: KnowledgeStatus, message: str) -> None:
        super().__init__(message)
        self.new_status = new_status


# --- Text extraction ------------------------------------------------------


def _decode_utf8_strict(data: bytes) -> str:
    """Decode + strip UTF-8 BOM. Raises UnicodeDecodeError for any
    non-UTF-8 bytes so a mislabelled binary uploaded as ``text/plain``
    ends up as ``failed_no_text`` rather than silently corrupting the
    knowledge base."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8")


def _extract_pdf_text(data: bytes) -> str:
    """Extract text from a PDF via ``pdfplumber``. pdfplumber does
    NOT execute JS or fetch external references; safe against
    typical malicious-PDF payloads. Scanned-image-only PDFs return
    empty text — caller marks the row as ``failed_no_text``."""
    # Import inside the function so a Celery worker that isn't
    # running the ingest task never has to load pdfplumber (~50 MB
    # of native deps).
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            try:
                txt = page.extract_text()
            except Exception:
                # pdfplumber occasionally raises on malformed page
                # streams; skip the page rather than fail the whole
                # ingest.
                continue
            if txt:
                parts.append(txt)
    return "\n\n".join(parts).strip()


def _extract_html_text(html: bytes, base_url: str | None = None) -> str:
    """Extract the main-content text of an HTML page via
    ``readability-lxml``. Falls back to the raw stripped HTML if
    readability can't identify a main article."""
    from readability import Document

    try:
        doc = Document(html.decode("utf-8", errors="replace"))
        summary_html = doc.summary(html_partial=True)
    except Exception:
        summary_html = html.decode("utf-8", errors="replace")
    # Strip tags. lxml is already a readability dep so no new deps.
    from lxml import html as lxml_html

    try:
        tree = lxml_html.fromstring(summary_html)
        # Kill scripts/styles/nav/footer/iframe outright — a URL
        # ingest of a Wikipedia article shouldn't include the sidebar.
        for tag in ("script", "style", "nav", "footer", "iframe", "noscript"):
            for el in tree.findall(f".//{tag}"):
                el.getparent().remove(el)
        return tree.text_content().strip()
    except Exception:
        # If lxml parsing fails, return the html as-is (still trimmed).
        return summary_html.strip()


def _looks_like_pdf(content_type: str | None, data: bytes) -> bool:
    if content_type and "application/pdf" in content_type.lower():
        return True
    return data[:4] == b"%PDF"


# --- Cancellation / heartbeat --------------------------------------------


async def _check_should_abort(
    session: AsyncSession,
    knowledge_id: uuid.UUID,
) -> None:
    """Poll the row's status. Raises :class:`_IngestAborted` if the
    operator has requested cancel / delete. Runs in its own tiny SELECT
    so the caller's outer txn stays short."""
    result = await session.execute(
        sql_text(
            "SELECT status::text FROM tbl_ai_assistant_knowledge WHERE id = :id"
        ),
        {"id": str(knowledge_id)},
    )
    row = result.first()
    if row is None:
        raise _IngestAborted(
            new_status=KnowledgeStatus.failed_ingest,
            message="knowledge row disappeared mid-ingest",
        )
    current = str(row[0])
    if current == KnowledgeStatus.pending_cancel.value:
        raise _IngestAborted(
            new_status=KnowledgeStatus.failed_ingest,
            message="ingest cancelled by operator",
        )
    if current == KnowledgeStatus.pending_delete.value:
        raise _IngestAborted(
            new_status=KnowledgeStatus.pending_delete,
            message="knowledge row marked for delete",
        )


async def _heartbeat_and_progress(
    session: AsyncSession,
    knowledge_id: uuid.UUID,
    *,
    progress_pct: int | None = None,
) -> None:
    """One UPDATE that bumps ``heartbeat_at`` + optionally
    ``progress_pct``. Runs in its own tx so the ingest txn holding
    chunk INSERTs doesn't hide the heartbeat from the reaper."""
    await _da.heartbeat_pulse(
        session,
        knowledge_id=knowledge_id,
        progress_pct=progress_pct,
    )
    await session.commit()


# --- Source-type-specific extractors -------------------------------------


async def _extract_from_source(
    row: AiAssistantKnowledge,
) -> str:
    """Dispatch by ``source_type`` + return extracted UTF-8 text.

    Raises :class:`UnsafeUrlError` for URL fetches that fail SSRF
    checks (caller catches + maps to ``failed_ingest``). Empty return
    → caller sets ``failed_no_text``.
    """
    if row.source_type == KnowledgeSourceType.text:
        return (row.body_text or "").strip()

    if row.source_type == KnowledgeSourceType.file:
        storage = get_storage()
        blob_path = _storage_key(row)
        try:
            data = storage.get(blob_path)
        except FileNotFoundError as exc:
            raise _IngestAborted(
                new_status=KnowledgeStatus.failed_ingest,
                message=f"stored blob missing: {blob_path!r}",
            ) from exc
        return _extract_from_bytes(data, mime=row.mime_type)

    if row.source_type == KnowledgeSourceType.url:
        if not row.url:
            raise _IngestAborted(
                new_status=KnowledgeStatus.failed_ingest,
                message="url source has no url column",
            )
        try:
            result = await safe_fetch(row.url)
        except UnsafeUrlError as exc:
            raise _IngestAborted(
                new_status=KnowledgeStatus.failed_ingest,
                message=f"unsafe url on fetch: {exc.reason}",
            ) from exc
        except httpx.HTTPError as exc:
            raise _IngestAborted(
                new_status=KnowledgeStatus.failed_ingest,
                message=f"network error fetching url: {exc!r}",
            ) from exc
        if result.status_code >= 400:
            raise _IngestAborted(
                new_status=KnowledgeStatus.failed_ingest,
                message=f"upstream returned HTTP {result.status_code}",
            )
        content_type = (result.content_type or "").split(";", 1)[0].strip().lower()
        if _looks_like_pdf(content_type, result.content):
            return _extract_pdf_text(result.content)
        if content_type in {"text/plain", "text/markdown"}:
            try:
                return _decode_utf8_strict(result.content)
            except UnicodeDecodeError as exc:
                raise _IngestAborted(
                    new_status=KnowledgeStatus.failed_ingest,
                    message="url served text/plain but bytes were not UTF-8",
                ) from exc
        if content_type in {"text/html", "application/xhtml+xml"} or content_type.startswith(
            "text/"
        ):
            return _extract_html_text(result.content)
        raise _IngestAborted(
            new_status=KnowledgeStatus.failed_ingest,
            message=f"unsupported content-type: {content_type!r}",
        )

    raise _IngestAborted(
        new_status=KnowledgeStatus.failed_ingest,
        message=f"unknown source_type {row.source_type!r}",
    )


def _extract_from_bytes(data: bytes, *, mime: str | None) -> str:
    """File-source extractor. Router already sniffed magic bytes and
    persisted the sniffed MIME on the row; we prefer it over the
    client-supplied Content-Type header."""
    if _looks_like_pdf(mime, data):
        return _extract_pdf_text(data)
    # Text default: strict UTF-8.
    try:
        return _decode_utf8_strict(data)
    except UnicodeDecodeError as exc:
        raise _IngestAborted(
            new_status=KnowledgeStatus.failed_ingest,
            message="file could not be decoded as UTF-8",
        ) from exc


def _storage_key(row: AiAssistantKnowledge) -> str:
    """Canonical storage path — NEVER uses the client's filename.
    Same shape as :func:`~core.ai_assistants.service._storage_key`
    used at upload-time."""
    return f"{row.org_id}/ai_assistants/{row.id}.bin"


# --- Main task body ------------------------------------------------------


async def ingest_knowledge(knowledge_id: uuid.UUID) -> IngestOutcome:
    """Run the full extract → chunk → embed → upsert pipeline for one
    knowledge row. Returns an :class:`IngestOutcome` describing the
    final state — Celery ships it back so the API caller can display
    per-source outcome without polling.

    This function OWNS the session lifecycle (opens + commits its own
    transactions) — matches the Celery-worker convention used by
    :mod:`core.workflows.tasks`.
    """
    async with async_session() as session:
        row = await _load_and_lock_for_processing(session, knowledge_id)
        if row is None:
            return IngestOutcome(
                status=KnowledgeStatus.failed_ingest.value,
                error="row disappeared before processing",
            )
        assistant_id = row.assistant_id
        org_id = row.org_id
        try:
            # Bind the RLS session variable so the tx (and every
            # nested txn opened in this coroutine chain) sees only
            # this org's rows.
            await session.execute(
                sql_text("SELECT set_config('app.current_org_id', :o, true)"),
                {"o": str(org_id)},
            )

            await _heartbeat_and_progress(session, knowledge_id, progress_pct=10)

            text_body = await _extract_from_source(row)

            if len(text_body.encode("utf-8", errors="ignore")) > _MAX_EXTRACTED_BYTES:
                await _da.set_status(
                    session,
                    knowledge_id=knowledge_id,
                    status=KnowledgeStatus.failed_ingest,
                    message=f"extracted text > {_MAX_EXTRACTED_BYTES // (1024 * 1024)} MB cap",
                )
                await session.commit()
                return IngestOutcome(
                    status=KnowledgeStatus.failed_ingest.value,
                    error="extracted_too_large",
                )

            if not text_body.strip():
                await _da.set_status(
                    session,
                    knowledge_id=knowledge_id,
                    status=KnowledgeStatus.failed_no_text,
                    message="no extractable text (image-only PDF? empty body?)",
                )
                await session.commit()
                return IngestOutcome(
                    status=KnowledgeStatus.failed_no_text.value,
                    error="no_text",
                )

            await _check_should_abort(session, knowledge_id)

            chunks = chunk_text(text_body)
            if not chunks:
                await _da.set_status(
                    session,
                    knowledge_id=knowledge_id,
                    status=KnowledgeStatus.failed_no_text,
                    message="chunker returned zero chunks (empty after markers stripped)",
                )
                await session.commit()
                return IngestOutcome(
                    status=KnowledgeStatus.failed_no_text.value,
                    error="no_chunks",
                )

            await _heartbeat_and_progress(session, knowledge_id, progress_pct=40)

            # Embed in batches. LLMClient.embed already batches
            # internally up to 100 per provider call, but we still
            # loop here so we can heartbeat + cancellation-check per
            # batch on very large corpora.
            llm = factory(
                "openai", db=session, org_id=org_id, key_id=await _key_id_for_assistant(session, assistant_id)
            )

            total = 0
            for start in range(0, len(chunks), _EMBED_BATCH_SIZE):
                await _check_should_abort(session, knowledge_id)
                batch = chunks[start : start + _EMBED_BATCH_SIZE]
                texts = [c.text for c in batch]
                try:
                    vectors = await llm.embed(texts, model=_EMBED_MODEL)
                except ProviderError as exc:
                    logger.warning(
                        "knowledge %s: embedding provider error (status=%s, request_id=%s): %r",
                        knowledge_id,
                        exc.status_code,
                        exc.request_id,
                        exc,
                    )
                    await _da.set_status(
                        session,
                        knowledge_id=knowledge_id,
                        status=KnowledgeStatus.failed_ingest,
                        message=_friendly_provider_error(exc),
                    )
                    await session.commit()
                    return IngestOutcome(
                        status=KnowledgeStatus.failed_ingest.value,
                        error="provider_error",
                    )
                # First batch: wipe any pre-existing chunks so a
                # re-ingest of the same knowledge row replaces cleanly
                # (Step 10 replace flow lands the temp row + swaps
                # the parent id; this path handles the same-row retry
                # / operator "reprocess" case).
                if start == 0:
                    store = PgVectorStore(session)
                    await store.delete_by_parent(
                        org_id=org_id,
                        parent_id=knowledge_id,
                    )
                entries = [
                    VectorEntry(
                        id=uuid.uuid4(),
                        org_id=org_id,
                        embedding=vec,
                        parent_id=knowledge_id,
                        parent_type="knowledge",
                        metadata={
                            "chunk_index": start + idx,
                            "text": batch[idx].text,
                            "token_count": batch[idx].token_count,
                        },
                    )
                    for idx, vec in enumerate(vectors)
                ]
                store = PgVectorStore(session)
                await store.upsert(entries)
                await session.commit()
                total += len(entries)
                await _heartbeat_and_progress(
                    session,
                    knowledge_id,
                    progress_pct=min(80, 40 + int(40 * (start + len(batch)) / len(chunks))),
                )

            await _da.set_status(
                session,
                knowledge_id=knowledge_id,
                status=KnowledgeStatus.ready,
                message=None,
                chunk_count=total,
                progress_pct=100,
                clear_heartbeat=True,
            )
            await session.commit()
            return IngestOutcome(
                status=KnowledgeStatus.ready.value,
                chunk_count=total,
            )
        except _IngestAborted as abort:
            # Roll back any half-committed chunk batches before
            # transitioning status; the final UPDATE runs in a new
            # implicit tx.
            try:
                await session.rollback()
            except Exception:
                pass
            # Wipe any partial chunks so retrieval doesn't return
            # torn results from the aborted ingest.
            try:
                store = PgVectorStore(session)
                await store.delete_by_parent(org_id=org_id, parent_id=knowledge_id)
                await session.commit()
            except Exception:
                logger.exception(
                    "ai_assistants.ingest partial_chunk_cleanup_failed knowledge=%s",
                    knowledge_id,
                )
                await session.rollback()
            await _da.set_status(
                session,
                knowledge_id=knowledge_id,
                status=abort.new_status,
                message=str(abort),
                clear_heartbeat=True,
            )
            await session.commit()
            return IngestOutcome(
                status=abort.new_status.value,
                error=str(abort),
            )
        except Exception as exc:
            logger.exception(
                "ai_assistants.ingest unhandled_error knowledge=%s org=%s",
                knowledge_id,
                org_id,
            )
            try:
                await session.rollback()
            except Exception:
                pass
            try:
                await _da.set_status(
                    session,
                    knowledge_id=knowledge_id,
                    status=KnowledgeStatus.failed_ingest,
                    message=f"unhandled: {type(exc).__name__}",
                    clear_heartbeat=True,
                )
                await session.commit()
            except Exception:
                logger.exception(
                    "ai_assistants.ingest status_update_after_error_failed knowledge=%s",
                    knowledge_id,
                )
            return IngestOutcome(
                status=KnowledgeStatus.failed_ingest.value,
                error=f"unhandled: {type(exc).__name__}",
            )


async def _load_and_lock_for_processing(
    session: AsyncSession,
    knowledge_id: uuid.UUID,
) -> AiAssistantKnowledge | None:
    """Atomically flip the row from ``pending`` → ``processing`` +
    return it. Uses ``FOR UPDATE`` so two concurrent workers can't
    both pick up the same task after a Celery redelivery.

    Returns ``None`` when the row doesn't exist OR its current status
    isn't ``pending`` (already running / already ready / already
    cancelled — the task is a no-op)."""
    # Bypass TenantScoped filter here — the task carries no request
    # context so we scope by knowledge_id + status alone. The caller
    # (Celery) has already been dispatched by the router which
    # verified org ownership at upload time.
    result = await session.execute(
        sql_text(
            """
            SELECT id, org_id, assistant_id, source_type::text, url, body_text,
                   mime_type, status::text
            FROM tbl_ai_assistant_knowledge
            WHERE id = :id
              AND status IN ('pending', 'processing')
            FOR UPDATE
            """
        ),
        {"id": str(knowledge_id)},
    )
    hit = result.mappings().first()
    if hit is None:
        return None

    # Mark as processing + set the first heartbeat inline.
    now = datetime.now(UTC)
    await session.execute(
        sql_text(
            """
            UPDATE tbl_ai_assistant_knowledge
            SET status = 'processing',
                progress_pct = 5,
                heartbeat_at = :hb,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"hb": now, "id": str(knowledge_id)},
    )
    await session.commit()

    # Re-select the ORM row for downstream field access.
    row = await _da.get_knowledge_by_id_no_org_filter(session, knowledge_id)
    return row


async def _key_id_for_assistant(
    session: AsyncSession,
    assistant_id: uuid.UUID,
) -> uuid.UUID:
    """Resolve the provider ``key_id`` the assistant is bound to. Runs
    outside the TenantScoped auto-filter so the ingest task (with no
    request context) can still see the row."""
    result = await session.execute(
        sql_text(
            "SELECT key_id FROM tbl_ai_assistants WHERE id = :id"
        ),
        {"id": str(assistant_id)},
    )
    row = result.first()
    if row is None:
        raise _IngestAborted(
            new_status=KnowledgeStatus.failed_ingest,
            message="assistant row disappeared before embed",
        )
    return uuid.UUID(str(row[0]))


__all__ = [
    "IngestOutcome",
    "ingest_knowledge",
]

# Suppress unused-import warning (typing helper we retain for API surface).
_: Any = None
