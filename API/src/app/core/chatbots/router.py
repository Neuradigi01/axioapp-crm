"""HTTP routes for the chatbots module.

Ten endpoints under ``/api/v1/chatbots``. Trigger-dispatch subscriber
lands in Step 5; test-fire in Step 6; signed-URL interstitial in
Step 11.

The router NEVER executes SQL directly — every read + write goes
through :mod:`core.chatbots.service` (layered-architecture pin-test).

Exception → HTTP mapping (see :func:`_chatbot_http_map`):

  * :class:`ChatbotNotFound`         → 404
  * :class:`ChatbotVersionConflict`  → 409
  * :class:`InvalidGraph`            → 422 (carries ``reason``)
  * :class:`InvalidSaveTarget`       → 422 (carries ``reason``)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.chatbots import save_target_registry as save_targets
from src.app.core.chatbots import service as chatbots_service
from src.app.core.chatbots.exceptions import (
    ChatbotError,
    ChatbotNotFound,
    ChatbotVersionConflict,
    InvalidGraph,
    InvalidSaveTarget,
)
from src.app.core.chatbots.permissions import (
    PERM_DELETE,
    PERM_EDIT,
    PERM_PUBLISH,
    PERM_VIEW,
)
from src.app.core.chatbots.schemas import (
    ChatbotCreate,
    ChatbotImportRequest,
    ChatbotImportResult,
    ChatbotListItem,
    ChatbotRead,
    ChatbotStats,
    ChatbotUpdate,
    ChatbotVersionRead,
    TestFireRequest,
    TestFireResponse,
)
from src.app.core.users.models import User
from src.app.shared.context import get_context
from src.app.shared.db import get_db

router = APIRouter(prefix="/chatbots", tags=["Chat Bots"])


# --- helpers -------------------------------------------------------------


def _chatbot_http_map(exc: ChatbotError) -> HTTPException:
    """Translate chatbot domain exceptions into FastAPI HTTPException
    with the canonical status code per the Step-3 spec."""
    if isinstance(exc, ChatbotNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="chatbot not found",
        )
    if isinstance(exc, ChatbotVersionConflict):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "version_conflict",
                "message": str(exc),
            },
        )
    if isinstance(exc, InvalidGraph):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_graph", "reason": str(exc)},
        )
    if isinstance(exc, InvalidSaveTarget):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_save_target", "reason": str(exc)},
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="unexpected chatbot error",
    )


def _require_org_id() -> uuid.UUID:
    """Read the active request's org_id off the context. Behind
    ``require_permissions`` it's guaranteed populated; the defensive
    400 guards against a middleware skip."""
    ctx = get_context()
    if ctx.org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no organisation in request context",
        )
    return ctx.org_id


def _actor_user_id(user: User) -> uuid.UUID | None:
    """Best-effort user-id extraction for the UUID audit FKs.

    Post-DR.7 ``User.id`` is the bigint PK of ``tbl_user_login``; the
    UUID identity that every ``*_by_user_id`` audit column expects
    lives on ``User.legacy_uuid``. Returning ``user.id`` here
    surfaces the classic ``asyncpg`` cast error (``$N::UUID`` gets an
    int) — always resolve to ``legacy_uuid``. System tokens without a
    bound user record NULL."""
    return getattr(user, "legacy_uuid", None)


# --- save-target picker (mounted FIRST so '/save-targets' doesn't
# get swallowed by '/{chatbot_id}') ---------------------------------------


@router.get(
    "/save-targets",
    response_model=list[dict],
)
async def list_save_targets_endpoint(
    entity: str = Query(..., min_length=1, max_length=64),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_VIEW)),
) -> list[dict]:
    """Registry-driven picker source for Ask-* / Set-Custom-Field
    node editors. Returns bot-writable standard fields + all
    non-hidden custom fields for the org+entity. Sensitive
    (``role``, ``owner_id``, ``balance``, verification timestamps,
    ``pin_hash``) are never included."""
    org_id = _require_org_id()
    try:
        targets = await save_targets.list_save_targets(
            db,
            org_id=org_id,
            entity=entity,
        )
    except InvalidSaveTarget as exc:
        raise _chatbot_http_map(exc) from exc
    # Convert dataclasses to plain dicts for the JSON response — this
    # keeps the router's public contract stable if the internal
    # dataclass fields ever grow.
    return [
        {
            "entity": t.entity,
            "field_key": t.field_key,
            "display_label": t.display_label,
            "format": t.format,
            "is_custom": t.is_custom,
            "qualified_key": t.qualified_key,
        }
        for t in targets
    ]


# --- bot CRUD ------------------------------------------------------------


@router.get(
    "",
    response_model=list[ChatbotListItem],
)
async def list_chatbots_endpoint(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    category: str | None = Query(default=None, max_length=64),
    folder_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_VIEW)),
) -> list[ChatbotListItem]:
    org_id = _require_org_id()
    rows, _total = await chatbots_service.list_chatbots_service(
        db,
        org_id=org_id,
        status=status_filter,
        category=category,
        folder_id=folder_id,
        search=q,
        limit=limit,
        offset=offset,
    )
    return [ChatbotListItem.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=ChatbotRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_chatbot_endpoint(
    payload: ChatbotCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_EDIT)),
) -> ChatbotRead:
    org_id = _require_org_id()
    try:
        bot = await chatbots_service.create_chatbot_service(
            db,
            org_id=org_id,
            payload=payload,
            actor_user_id=_actor_user_id(user),
        )
    except ChatbotError as exc:
        raise _chatbot_http_map(exc) from exc
    return ChatbotRead.model_validate(bot)


@router.get(
    "/{chatbot_id}",
    response_model=ChatbotRead,
)
async def get_chatbot_endpoint(
    chatbot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_VIEW)),
) -> ChatbotRead:
    org_id = _require_org_id()
    try:
        bot = await chatbots_service.get_chatbot_service(
            db,
            org_id=org_id,
            chatbot_id=chatbot_id,
        )
    except ChatbotError as exc:
        raise _chatbot_http_map(exc) from exc
    return ChatbotRead.model_validate(bot)


@router.patch(
    "/{chatbot_id}",
    response_model=ChatbotRead,
)
async def patch_chatbot_endpoint(
    chatbot_id: uuid.UUID,
    payload: ChatbotUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_EDIT)),
) -> ChatbotRead:
    org_id = _require_org_id()
    try:
        bot = await chatbots_service.save_chatbot_service(
            db,
            org_id=org_id,
            chatbot_id=chatbot_id,
            payload=payload,
            actor_user_id=_actor_user_id(user),
        )
    except ChatbotError as exc:
        raise _chatbot_http_map(exc) from exc
    return ChatbotRead.model_validate(bot)


@router.post(
    "/{chatbot_id}/publish",
    response_model=ChatbotRead,
)
async def publish_chatbot_endpoint(
    chatbot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_PUBLISH)),
) -> ChatbotRead:
    org_id = _require_org_id()
    try:
        bot = await chatbots_service.publish_chatbot_service(
            db,
            org_id=org_id,
            chatbot_id=chatbot_id,
            actor_user_id=_actor_user_id(user),
        )
    except ChatbotError as exc:
        raise _chatbot_http_map(exc) from exc
    return ChatbotRead.model_validate(bot)


@router.post(
    "/{chatbot_id}/pause",
    response_model=ChatbotRead,
)
async def pause_chatbot_endpoint(
    chatbot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_EDIT)),
) -> ChatbotRead:
    org_id = _require_org_id()
    try:
        bot = await chatbots_service.pause_chatbot_service(
            db,
            org_id=org_id,
            chatbot_id=chatbot_id,
            actor_user_id=_actor_user_id(user),
        )
    except ChatbotError as exc:
        raise _chatbot_http_map(exc) from exc
    return ChatbotRead.model_validate(bot)


@router.delete(
    "/{chatbot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def archive_chatbot_endpoint(
    chatbot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_DELETE)),
) -> Response:
    org_id = _require_org_id()
    try:
        await chatbots_service.archive_chatbot_service(
            db,
            org_id=org_id,
            chatbot_id=chatbot_id,
            actor_user_id=_actor_user_id(user),
        )
    except ChatbotError as exc:
        raise _chatbot_http_map(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- version history + rollback ------------------------------------------


@router.get(
    "/{chatbot_id}/versions",
    response_model=list[ChatbotVersionRead],
)
async def list_versions_endpoint(
    chatbot_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_VIEW)),
) -> list[ChatbotVersionRead]:
    org_id = _require_org_id()
    try:
        rows = await chatbots_service.list_versions_service(
            db,
            org_id=org_id,
            chatbot_id=chatbot_id,
            limit=limit,
        )
    except ChatbotError as exc:
        raise _chatbot_http_map(exc) from exc
    return [ChatbotVersionRead.model_validate(r) for r in rows]


@router.get(
    "/{chatbot_id}/stats",
    response_model=ChatbotStats,
)
async def get_stats_endpoint(
    chatbot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_VIEW)),
) -> ChatbotStats:
    """Aggregate stats: run counts by status + completion rate + top
    executed nodes. Read-only, computed on demand — no cache. Test-mode
    runs excluded."""
    org_id = _require_org_id()
    try:
        stats = await chatbots_service.get_stats_service(
            db, org_id=org_id, chatbot_id=chatbot_id
        )
    except ChatbotError as exc:
        raise _chatbot_http_map(exc) from exc
    return ChatbotStats.model_validate(stats)


@router.get(
    "/{chatbot_id}/export",
    response_model=dict,
)
async def export_chatbot_endpoint(
    chatbot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_VIEW)),
) -> dict:
    """Portable bot export. Returns the envelope described by
    :class:`schemas.ChatbotExportEnvelope`. Read-gated — anyone
    who can see the bot can export it (analogous to the
    workflows export)."""
    org_id = _require_org_id()
    try:
        return await chatbots_service.export_chatbot_service(
            db, org_id=org_id, chatbot_id=chatbot_id
        )
    except ChatbotError as exc:
        raise _chatbot_http_map(exc) from exc


@router.post(
    "/import",
    response_model=ChatbotImportResult,
    status_code=status.HTTP_201_CREATED,
)
async def import_chatbot_endpoint(
    payload: ChatbotImportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_EDIT)),
) -> ChatbotImportResult:
    """Create a new bot from an export envelope. Any custom-field /
    template references that don't exist in the target org are
    surfaced as ``conflicts`` — the bot lands as a draft and the
    operator remaps references before publishing."""
    org_id = _require_org_id()
    try:
        result = await chatbots_service.import_chatbot_service(
            db,
            org_id=org_id,
            envelope=payload.envelope.model_dump(),
            name_override=payload.name_override,
            actor_user_id=_actor_user_id(user),
        )
    except ChatbotError as exc:
        raise _chatbot_http_map(exc) from exc
    return ChatbotImportResult(**result)


@router.post(
    "/{chatbot_id}/test-fire",
    response_model=TestFireResponse,
)
async def test_fire_endpoint(
    chatbot_id: uuid.UUID,
    payload: TestFireRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_EDIT)),
) -> TestFireResponse:
    """Dry-run a bot with a synthetic inbound. Case #22 /
    Decision §17: ``dry_run=true`` is enforced server-side, sends
    are transcript-only, save-to writes go to per-run scratch, and
    the test run auto-deletes after 24h.

    Requires ``chatbots.edit`` (this is authoring, not consumption)."""
    org_id = _require_org_id()
    try:
        result = await chatbots_service.test_fire_service(
            db,
            org_id=org_id,
            chatbot_id=chatbot_id,
            simulated_inbound_text=payload.simulated_inbound_text,
            simulated_channel=payload.simulated_channel,
            simulated_contact_id=payload.simulated_contact_id,
            simulated_conversation_id=payload.simulated_conversation_id,
            simulated_is_first_message=payload.simulated_is_first_message,
        )
    except ChatbotError as exc:
        raise _chatbot_http_map(exc) from exc
    return TestFireResponse(**result)


@router.post(
    "/{chatbot_id}/versions/{version_id}/rollback",
    response_model=ChatbotRead,
)
async def rollback_version_endpoint(
    chatbot_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_PUBLISH)),
) -> ChatbotRead:
    """Restore a prior version's graph + trigger_config. Requires
    ``chatbots.publish`` because a rollback effectively pushes new
    authoritative state into a running bot."""
    org_id = _require_org_id()
    try:
        bot = await chatbots_service.rollback_to_version_service(
            db,
            org_id=org_id,
            chatbot_id=chatbot_id,
            version_id=version_id,
            actor_user_id=_actor_user_id(user),
        )
    except ChatbotError as exc:
        raise _chatbot_http_map(exc) from exc
    return ChatbotRead.model_validate(bot)
