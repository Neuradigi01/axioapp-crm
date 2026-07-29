"""Keyword-rule engine
(whatsapp-platform-upgrade Step 17).

Two entry points:

  * :func:`evaluate_rules` — pure-function tester used by both the
    real inbound dispatcher and the dry-run endpoint. Walks active
    rules in `priority` ascending order; first match wins. Each
    match type (``contains``/``exact``/``regex``) has its own helper.

  * :func:`dispatch_keyword_rules` — production path called from
    `receive_webhook`. Evaluates rules, applies cooldown, dispatches
    every action of the matched rule via the action handlers
    (``reply_text`` / ``reply_template`` / ``tag_conversation`` /
    ``assign_to_user`` / ``escalate_to_ai``).

Cooldown is a Redis-first token bucket keyed on
``(rule_id, contact_external_id)`` via
:mod:`src.app.shared.rate_limit_shared`. Falls back to a process-
local map when Redis is unreachable (dev shells, transient blips)
so keyword rules still work in single-worker setups. Was originally
process-local only — under horizontal scale that let a contact
receive N duplicate auto-replies in the same 60s window.

Regex match safety: pattern length capped at the schema layer
(200 chars); evaluation wrapped in try/except so an operator
typo doesn't crash inbound webhook handling.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.shared.rate_limit_shared import (
    acquire_cooldown as _acquire_cooldown,
    is_on_cooldown as _is_on_cooldown,
)

from src.app.core import audit
from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppNotConnected,
    resolve_whatsapp_adapter,
)
from src.app.core.conversations.models import (
    Conversation,
    Message,
    MessageDirection,
)
from src.app.core.conversations.tags_service import assign_tag
from src.app.core.integrations.whatsapp.models import (
    KeywordActionType,
    KeywordMatchType,
    WhatsAppKeywordAction,
    WhatsAppKeywordRule,
    WhatsAppTemplate,
)

logger = logging.getLogger(__name__)


# Default cooldown: same rule + same contact can fire once per 60s.
# Prevents reply loops when the operator's reply text would itself
# match the same keyword.
_COOLDOWN_SECONDS = 60

# Cap how long we'll spend on regex matching against an inbound
# message. Python's re module doesn't enforce a hard wall-clock
# timeout, but capping pattern length (schema) + body length
# (WhatsApp 4096) gives us bounded worst-case behaviour.
_REGEX_MAX_PATTERN_LEN = 200


# --- Cross-worker cooldown -----------------------------------------------
#
# Backed by ``rate_limit_shared`` — Redis-first with an in-process
# fallback for dev shells and outages. The single-worker key shape
# ``(rule_id, contact_key)`` becomes the Redis-safe string
# ``kwrl:{rule_id}:{contact_key}`` so distinct rules can't collide.


def _cooldown_key(rule_id: uuid.UUID, contact_key: str) -> str:
    return f"kwrl:{rule_id}:{contact_key}"


async def _cooldown_active(rule_id: uuid.UUID, contact_key: str) -> bool:
    """Read-only check — used by the dry-run test path where we don't
    want to actually consume a cooldown slot."""
    return await _is_on_cooldown(_cooldown_key(rule_id, contact_key))


async def _try_acquire_cooldown(rule_id: uuid.UUID, contact_key: str) -> bool:
    """Atomically claim the cooldown slot for this rule+contact.

    Returns True when the caller "won" (they should proceed with the
    action dispatch), False when someone else already holds the slot
    (this inbound is on cooldown — silently skip).

    Uses the same primitive `SET NX PX` (Redis) / lock-checked map
    (in-process). Previously ``dispatch_keyword_rules`` did a check-
    then-set with two separate calls; under horizontal scale that
    left a small race where two workers could both pass the check
    before either set the flag."""
    return await _acquire_cooldown(
        _cooldown_key(rule_id, contact_key), _COOLDOWN_SECONDS
    )


# --- match helpers --------------------------------------------------------


def _match_contains(keywords: list[str], text: str) -> bool:
    """Case-insensitive substring match — ANY keyword present in the
    inbound text triggers the rule."""
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords if kw)


def _match_exact(keywords: list[str], text: str) -> bool:
    """Case-insensitive whole-string match against any keyword."""
    stripped = text.strip().lower()
    return any(kw.strip().lower() == stripped for kw in keywords if kw)


def _match_regex(keywords: list[str], text: str) -> bool:
    """Try each keyword as a regex. Length-capped + try/except wrapped
    so a bad pattern returns False instead of crashing."""
    for pattern in keywords:
        if not pattern or len(pattern) > _REGEX_MAX_PATTERN_LEN:
            continue
        try:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return True
        except re.error:
            logger.warning("keyword_engine: invalid regex pattern %r", pattern)
            continue
    return False


def _rule_matches(rule: WhatsAppKeywordRule, text: str) -> bool:
    if not rule.enabled or not rule.keywords:
        return False
    if not text:
        return False
    if rule.match_type == KeywordMatchType.contains:
        return _match_contains(rule.keywords, text)
    if rule.match_type == KeywordMatchType.exact:
        return _match_exact(rule.keywords, text)
    if rule.match_type == KeywordMatchType.regex:
        return _match_regex(rule.keywords, text)
    return False


# --- public read ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleEvaluationResult:
    rule: WhatsAppKeywordRule | None
    actions: list[WhatsAppKeywordAction]


async def evaluate_rules(
    session: AsyncSession,
    *,
    text: str,
) -> RuleEvaluationResult:
    """Pure-read evaluation — returns the first matching rule + its
    actions. Used by both the live dispatcher and the dry-run
    endpoint. RLS auto-scopes to the active org via TenantScoped."""
    rules = (
        (
            await session.execute(
                select(WhatsAppKeywordRule)
                .where(WhatsAppKeywordRule.enabled.is_(True))
                .order_by(
                    WhatsAppKeywordRule.priority.asc(),
                    WhatsAppKeywordRule.created_at.asc(),
                )
            )
        )
        .scalars()
        .all()
    )

    for rule in rules:
        if _rule_matches(rule, text):
            actions = (
                (
                    await session.execute(
                        select(WhatsAppKeywordAction)
                        .where(WhatsAppKeywordAction.rule_id == rule.id)
                        .order_by(
                            WhatsAppKeywordAction.position.asc(),
                            WhatsAppKeywordAction.created_at.asc(),
                        )
                    )
                )
                .scalars()
                .all()
            )
            return RuleEvaluationResult(rule=rule, actions=list(actions))

    return RuleEvaluationResult(rule=None, actions=[])


# --- action handlers ------------------------------------------------------


async def _action_reply_text(
    session: AsyncSession,
    *,
    conversation: Conversation,
    config: dict[str, Any],
) -> None:
    """Free-text reply. Skipped silently when the config is missing
    a body or when the action would fire against a non-WhatsApp
    conversation (defensive — engine only runs for whatsapp)."""
    body = (config or {}).get("text")
    if not isinstance(body, str) or not body.strip():
        return
    adapter = await resolve_whatsapp_adapter(session)
    ref = await adapter.send(
        org_id=conversation.org_id,
        external_id=conversation.external_id,
        text=body,
        attachments=[],
    )
    now = datetime.now(UTC)
    sent_at = ref.sent_at or now
    msg = Message(
        org_id=conversation.org_id,
        conversation_id=conversation.id,
        direction=MessageDirection.out,
        sender_user_id=None,
        text=body,
        attachments=[],
        channel_message_id=ref.channel_message_id,
        payload={
            "keyword_rule_action": "reply_text",
            "adapter_ref": ref.channel_message_id,
        },
        sent_at=sent_at,
    )
    session.add(msg)
    conversation.last_message_at = sent_at


async def _action_reply_template(
    session: AsyncSession,
    *,
    conversation: Conversation,
    config: dict[str, Any],
) -> None:
    raw_id = (config or {}).get("template_id")
    if not isinstance(raw_id, str):
        return
    try:
        template_id = uuid.UUID(raw_id)
    except (TypeError, ValueError):
        return
    template = (
        await session.execute(
            select(WhatsAppTemplate).where(
                WhatsAppTemplate.id == template_id,
                WhatsAppTemplate.status == "APPROVED",
            )
        )
    ).scalar_one_or_none()
    if template is None:
        return
    adapter = await resolve_whatsapp_adapter(session)
    ref = await adapter.send_template(
        org_id=conversation.org_id,
        external_id=conversation.external_id,
        template_name=template.name,
        language=template.language,
        variables={},
        header_type=template.header_type,
        header_text=template.header_text,
    )
    now = datetime.now(UTC)
    sent_at = ref.sent_at or now
    msg = Message(
        org_id=conversation.org_id,
        conversation_id=conversation.id,
        direction=MessageDirection.out,
        sender_user_id=None,
        text=template.body,
        attachments=[],
        channel_message_id=ref.channel_message_id,
        payload={
            "keyword_rule_action": "reply_template",
            "template_id": str(template.id),
            "adapter_ref": ref.channel_message_id,
        },
        sent_at=sent_at,
    )
    session.add(msg)
    conversation.last_message_at = sent_at


async def _action_tag_conversation(
    session: AsyncSession,
    *,
    conversation: Conversation,
    config: dict[str, Any],
    actor_id: uuid.UUID | None,
) -> None:
    raw_id = (config or {}).get("tag_id")
    if not isinstance(raw_id, str):
        return
    try:
        tag_id = uuid.UUID(raw_id)
    except (TypeError, ValueError):
        return
    try:
        await assign_tag(
            session,
            actor_id=actor_id or conversation.org_id,
            org_id=conversation.org_id,
            conversation_id=conversation.id,
            tag_id=tag_id,
        )
    except Exception:
        logger.exception(
            "keyword_engine: tag assignment failed conv=%s tag=%s",
            conversation.id,
            tag_id,
        )


def _action_assign_to_user(
    *,
    conversation: Conversation,
    config: dict[str, Any],
) -> None:
    """In-place mutation — caller commits. Resolving the target user
    against `tbl_organization_members` is the operator's job at
    config time; if they configured a stale id, the conversation
    just shows an unknown assignee badge (the UI handles that)."""
    raw_id = (config or {}).get("user_id")
    if not isinstance(raw_id, str):
        return
    try:
        user_uuid = uuid.UUID(raw_id)
    except (TypeError, ValueError):
        return
    conversation.assigned_to_id = user_uuid


def _action_escalate_to_ai(conversation: Conversation) -> None:
    """Flip the AI-handling flag on. Step 19 wires the actual AI."""
    conversation.ai_handling = True


# --- dispatch -------------------------------------------------------------


async def dispatch_keyword_rules(
    session: AsyncSession,
    *,
    conversation: Conversation,
    text: str | None,
) -> uuid.UUID | None:
    """Live evaluation + action dispatch. Called from
    `receive_webhook` AFTER the auto-reply pipeline.

    Returns the matched rule id (for logging / observability) or
    None. Failures inside any action handler are caught + logged;
    a broken rule doesn't roll back the inbound message persist."""
    if not text:
        return None

    try:
        result = await evaluate_rules(session, text=text)
    except Exception:
        logger.exception("keyword_engine: rule evaluation failed")
        return None

    rule = result.rule
    if rule is None:
        return None

    contact_key = conversation.external_id or str(conversation.contact_id) or "anon"
    # Atomic acquire — either we win the slot (proceed) or the slot's
    # already held (skip). Replaces the prior check-then-set which
    # was racy under horizontal scale.
    acquired = await _try_acquire_cooldown(rule.id, contact_key)
    if not acquired:
        logger.info(
            "keyword_engine: rule %s on cooldown for %s",
            rule.id,
            contact_key,
        )
        return None

    for action in result.actions:
        config = action.action_config or {}
        action_type = action.action_type
        try:
            if action_type == KeywordActionType.reply_text:
                await _action_reply_text(session, conversation=conversation, config=config)
            elif action_type == KeywordActionType.reply_template:
                await _action_reply_template(session, conversation=conversation, config=config)
            elif action_type == KeywordActionType.tag_conversation:
                await _action_tag_conversation(
                    session,
                    conversation=conversation,
                    config=config,
                    actor_id=None,
                )
            elif action_type == KeywordActionType.assign_to_user:
                _action_assign_to_user(conversation=conversation, config=config)
            elif action_type == KeywordActionType.escalate_to_ai:
                _action_escalate_to_ai(conversation)
        except WhatsAppNotConnected:
            logger.info(
                "keyword_engine: skipped %s — org not connected",
                action_type.value,
            )
        except Exception:
            logger.exception(
                "keyword_engine: action %s failed for rule %s",
                action_type.value,
                rule.id,
            )

    await session.commit()
    await session.refresh(conversation)
    await audit.log(
        "conversations.keyword_rule_fired",
        entity_type="conversation",
        entity_id=conversation.id,
        after={
            "rule_id": str(rule.id),
            "rule_name": rule.name,
            "action_count": len(result.actions),
        },
    )
    return rule.id


__all__ = [
    "RuleEvaluationResult",
    "dispatch_keyword_rules",
    "evaluate_rules",
]
