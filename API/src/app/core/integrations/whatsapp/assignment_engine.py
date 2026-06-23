"""Auto-assignment engine
(whatsapp-platform-upgrade Step 18).

One entry point — :func:`dispatch_assignment` — invoked from
``conversations.service.receive_webhook`` after the keyword pipeline.
Skips when the conversation already has an `assigned_to_id` (set by
manual triage, a keyword `assign_to_user` action, or an earlier
auto-assignment).

Walks enabled rules in `priority` ascending order; first rule that
returns a user wins. Four strategies:

  * ``round_robin``   — cycle through ``eligible_user_ids`` using the
    rule row's ``last_assigned_user_id`` cursor. ``SELECT FOR UPDATE``
    on the rule row serialises concurrent webhooks so two inbound
    messages don't both pick the same user.

  * ``load_balanced`` — pick the eligible user with the fewest open
    (`status='open'`) WhatsApp conversations. Tiebreak: alphabetic
    by user id for determinism. Optional ``cap_per_user`` skips
    users already at the cap.

  * ``tag_based``     — map ``{tag_id: user_id}``. The conversation's
    current tags (just-set by Step 17's `tag_conversation` action,
    or pre-existing) are intersected with the mapping; first hit
    wins. Skips silently when no tag matches.

  * ``team_based``    — assigns to a user from the team's
    `tbl_organization_members` list. Falls back to NULL when the
    team is empty or the teams concept isn't installed.

Offline filter: every strategy skips users whose `tbl_user_login.is_active`
is False. Future steps can extend with `last_seen_at`.

Business-hours skip: when `rule.skip_outside_hours=True` and the
current time falls outside the org's Step-11 schedule, the rule
returns NULL and the next rule (or no-op) takes over.
"""
from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    ConversationStatus,
    ConversationTagAssignment,
)
from src.app.core.integrations.whatsapp.auto_reply import (
    is_within_business_hours,
)
from src.app.core.integrations.whatsapp.connect import get_active_config
from src.app.core.integrations.whatsapp.models import (
    AssignmentStrategy,
    WhatsAppAccountConfig,
    WhatsAppAssignmentRule,
)
from src.app.core.users.models import OrganizationMember, User

logger = logging.getLogger(__name__)


# --- eligibility filter ------------------------------------------------


async def _active_user_ids(
    session: AsyncSession,
    *,
    candidate_ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    """Filter candidate user UUIDs down to those whose
    `tbl_user_login.is_active = TRUE`. Preserves the input order
    (round-robin needs the list to be stable across calls)."""
    if not candidate_ids:
        return []
    rows = (
        await session.execute(
            select(User.legacy_uuid).where(
                User.legacy_uuid.in_(candidate_ids),
                User.is_active.is_(True),
            )
        )
    ).scalars().all()
    active_set = set(rows)
    return [uid for uid in candidate_ids if uid in active_set]


async def _load_counts(
    session: AsyncSession,
    *,
    user_ids: list[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """Return ``{user_id: open_conversation_count}`` for the active
    org's WhatsApp conversations. Users with zero open conversations
    do NOT appear in the result; the caller must default to 0."""
    if not user_ids:
        return {}
    rows = (
        await session.execute(
            select(
                Conversation.assigned_to_id,
                func.count(Conversation.id),
            )
            .where(Conversation.channel == ConversationChannel.whatsapp)
            .where(Conversation.assigned_to_id.in_(user_ids))
            .where(Conversation.status == ConversationStatus.open)
            .group_by(Conversation.assigned_to_id)
        )
    ).all()
    return {uid: int(count) for uid, count in rows}


async def _conversation_tag_ids(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
) -> set[uuid.UUID]:
    rows = (
        await session.execute(
            select(ConversationTagAssignment.tag_id).where(
                ConversationTagAssignment.conversation_id == conversation_id
            )
        )
    ).scalars().all()
    return set(rows)


# --- strategy pickers --------------------------------------------------


def _coerce_uuid_list(raw: Any) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    if not isinstance(raw, list):
        return out
    for entry in raw:
        try:
            out.append(uuid.UUID(str(entry)))
        except (TypeError, ValueError):
            continue
    return out


async def _pick_round_robin(
    session: AsyncSession,
    *,
    rule: WhatsAppAssignmentRule,
) -> Optional[uuid.UUID]:
    """Locks the rule row, advances the cursor, returns the next
    active eligible user.

    Lock ensures concurrent webhooks see consistent state: two
    parallel `receive_webhook` calls will serialise on the row and
    each pick a different next user, not the same one twice."""
    locked = (
        await session.execute(
            select(WhatsAppAssignmentRule)
            .where(WhatsAppAssignmentRule.id == rule.id)
            .with_for_update()
        )
    ).scalar_one()
    eligible = _coerce_uuid_list(
        (locked.config or {}).get("eligible_user_ids")
    )
    active = await _active_user_ids(session, candidate_ids=eligible)
    if not active:
        return None
    last = locked.last_assigned_user_id
    if last is None or last not in active:
        chosen = active[0]
    else:
        idx = active.index(last)
        chosen = active[(idx + 1) % len(active)]
    locked.last_assigned_user_id = chosen
    return chosen


async def _pick_load_balanced(
    session: AsyncSession,
    *,
    rule: WhatsAppAssignmentRule,
) -> Optional[uuid.UUID]:
    """Pick the eligible user with the fewest open conversations.
    Tiebreak: alphabetic by user id. Respects `cap_per_user` when set."""
    eligible = _coerce_uuid_list(
        (rule.config or {}).get("eligible_user_ids")
    )
    active = await _active_user_ids(session, candidate_ids=eligible)
    if not active:
        return None
    counts = await _load_counts(session, user_ids=active)
    cap_raw = (rule.config or {}).get("cap_per_user")
    cap = (
        int(cap_raw)
        if isinstance(cap_raw, int) and cap_raw > 0
        else None
    )
    # Sort: count asc, then user_id string asc (stable tiebreak).
    candidates = [
        (counts.get(uid, 0), str(uid), uid) for uid in active
    ]
    candidates.sort(key=lambda c: (c[0], c[1]))
    for count, _str_id, uid in candidates:
        if cap is not None and count >= cap:
            continue
        return uid
    return None


async def _pick_tag_based(
    session: AsyncSession,
    *,
    rule: WhatsAppAssignmentRule,
    conversation_id: uuid.UUID,
) -> Optional[uuid.UUID]:
    """Map the conversation's current tags through ``mapping`` and
    return the first eligible user. Skips silently when no tag
    matches or the mapped user is inactive."""
    mapping = (rule.config or {}).get("mapping")
    if not isinstance(mapping, dict) or not mapping:
        return None
    # Normalise the mapping keys to UUIDs so a string-vs-uuid
    # mismatch from JSONB storage doesn't silently miss.
    parsed: dict[uuid.UUID, uuid.UUID] = {}
    for k, v in mapping.items():
        try:
            parsed[uuid.UUID(str(k))] = uuid.UUID(str(v))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return None

    conv_tags = await _conversation_tag_ids(
        session, conversation_id=conversation_id
    )
    if not conv_tags:
        return None
    # First-match order is "any matching tag" → no stable ordering
    # guaranteed for multi-tag conversations; we sort by tag UUID
    # for determinism.
    for tag_id in sorted(parsed.keys() & conv_tags, key=str):
        candidate = parsed[tag_id]
        active = await _active_user_ids(
            session, candidate_ids=[candidate]
        )
        if active:
            return active[0]
    return None


async def _pick_team_based(
    session: AsyncSession,
    *,
    rule: WhatsAppAssignmentRule,
) -> Optional[uuid.UUID]:
    """Pick a random active member of the team's `tbl_organization_members`
    set. The teams concept isn't fully wired yet — this implementation
    treats `team_id` as a placeholder org-membership filter, picking
    any active org member. Future Phase work can swap in the real
    teams join without a schema change."""
    raw = (rule.config or {}).get("team_id")
    if not raw:
        return None
    rows = (
        await session.execute(
            select(User.legacy_uuid)
            .join(
                OrganizationMember,
                OrganizationMember.user_member_id == User.id,
            )
            .where(
                OrganizationMember.is_active.is_(True),
                User.is_active.is_(True),
            )
        )
    ).scalars().all()
    if not rows:
        return None
    return random.choice(list(rows))


# --- pipeline ----------------------------------------------------------


async def dispatch_assignment(
    session: AsyncSession,
    *,
    conversation: Conversation,
) -> Optional[uuid.UUID]:
    """Run the assignment pipeline for a (still-unassigned) WhatsApp
    conversation. Returns the assigned user_id (also written to
    `conversation.assigned_to_id`) or None.

    Skips entirely when:
      * conversation already has an `assigned_to_id`
      * no enabled rules exist
      * every rule's strategy returns None (e.g. all users offline)
    """
    if conversation.assigned_to_id is not None:
        return None

    rules = (
        await session.execute(
            select(WhatsAppAssignmentRule)
            .where(WhatsAppAssignmentRule.enabled.is_(True))
            .order_by(
                WhatsAppAssignmentRule.priority.asc(),
                WhatsAppAssignmentRule.created_at.asc(),
            )
        )
    ).scalars().all()
    if not rules:
        return None

    # Optionally load business hours for skip-outside-hours rules.
    config: Optional[WhatsAppAccountConfig] = None
    business_hours: Optional[list[dict[str, Any]]] = None
    now = datetime.now(timezone.utc)

    for rule in rules:
        if rule.skip_outside_hours:
            if config is None:
                try:
                    bundle = await get_active_config(session)
                    if bundle is not None:
                        _, config = bundle
                        business_hours = (
                            list(config.business_hours or [])
                            if config.business_hours
                            else []
                        )
                except Exception:
                    logger.exception(
                        "assignment_engine: business-hours lookup failed"
                    )
                    business_hours = None
            if (
                business_hours is not None
                and not is_within_business_hours(
                    business_hours, now=now
                )
            ):
                continue

        chosen: Optional[uuid.UUID] = None
        try:
            if rule.strategy == AssignmentStrategy.round_robin:
                chosen = await _pick_round_robin(session, rule=rule)
            elif rule.strategy == AssignmentStrategy.load_balanced:
                chosen = await _pick_load_balanced(session, rule=rule)
            elif rule.strategy == AssignmentStrategy.tag_based:
                chosen = await _pick_tag_based(
                    session,
                    rule=rule,
                    conversation_id=conversation.id,
                )
            elif rule.strategy == AssignmentStrategy.team_based:
                chosen = await _pick_team_based(session, rule=rule)
        except Exception:
            logger.exception(
                "assignment_engine: rule %s strategy %s raised",
                rule.id,
                rule.strategy.value,
            )
            continue

        if chosen is not None:
            conversation.assigned_to_id = chosen
            await session.commit()
            await session.refresh(conversation)
            await audit.log(
                "conversations.assignment_rule_fired",
                entity_type="conversation",
                entity_id=conversation.id,
                after={
                    "rule_id": str(rule.id),
                    "rule_name": rule.name,
                    "strategy": rule.strategy.value,
                    "assigned_to_user_id": str(chosen),
                },
            )
            return chosen

    return None


__all__ = [
    "_active_user_ids",
    "_load_counts",
    "_pick_load_balanced",
    "_pick_round_robin",
    "_pick_tag_based",
    "dispatch_assignment",
]
