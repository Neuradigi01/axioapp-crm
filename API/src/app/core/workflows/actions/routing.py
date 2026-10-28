"""Routing action handlers — Step 9.

Five handlers register against the action registry:

  * ``routing.round_robin``   — cycles through a configured user pool
    in deterministic order. Pointer state lives on
    ``tbl_org_settings.routing_state`` keyed by ``pool_spec`` string.
  * ``routing.least_loaded``  — picks the user with the fewest open
    leads (``status != 'won' AND status != 'lost'``). Tie-broken by
    the lead's ``last_activity_at`` ascending so the rep idle for
    longer wins.
  * ``routing.territory``     — picks the user whose configured
    territories include the lead's ``region`` / ``state`` / ``city``.
    Falls through to ``config.fallback`` (default ``round_robin``)
    when no user matches.
  * ``routing.skill``         — picks the user whose configured
    skills include the lead's ``skill_required`` value (typically a
    custom field). Falls through to ``config.fallback`` (default
    ``round_robin``).
  * ``routing.specific_user`` — assigns to a static configured
    ``user_id``. Useful for "always send to the founder" patterns.

Each handler returns
``ActionResult(output={'assigned_user_id', 'assignment_method',
'pool_size'})`` so downstream nodes can branch on it (e.g.
``send.email`` to notify the assignee).

Assignment goes through the origin module's ``reassign_lead`` /
``reassign_contact`` (NOT the DAL) so the activities timeline +
audit emits + permission checks fire the same as a manual reassign.

Pool spec grammar (``config.pool``):
  * ``"role:<role_name>"``  — all active members in the role.
  * ``"users:<csv of uuids>"`` — explicit user list.

The territory / skill maps live INLINE in the node config (no
``tbl_users.metadata`` column on the existing schema) — operators
supply ``territory_map: {<user_uuid>: ["mumbai", "delhi"], ...}``
or ``skill_map: {...}`` so the resolver can pick without needing
a user-side metadata refactor. Future work: lift the maps into a
per-user JSONB column once an operator asks for it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.workflows.actions import register_action

logger = logging.getLogger(__name__)


# --- ActionResult helpers ------------------------------------------------


def _result_assigned(
    *,
    assigned_user_id: uuid.UUID,
    method: str,
    pool_size: int,
):
    from src.app.core.workflows.engine import ActionResult

    return ActionResult(
        output={
            "assigned_user_id": str(assigned_user_id),
            "assignment_method": method,
            "pool_size": pool_size,
        }
    )


def _result_skipped(reason: str, **extra: Any):
    from src.app.core.workflows.engine import ActionResult

    payload: dict[str, Any] = dict(extra) if extra else {}
    payload["skip_reason"] = reason
    return ActionResult(skip_reason=reason, output=payload)


# --- Pool resolution -----------------------------------------------------


async def _resolve_pool(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    pool_spec: str,
) -> list[uuid.UUID]:
    """Resolve ``pool_spec`` to a list of user_uuid candidates.

    Grammar:
      * ``"role:<role_name>"`` — every active OrganizationMember in
        the role (filtered to active memberships only).
      * ``"users:<csv>"``      — comma-separated UUIDs. Bad UUIDs
        are dropped silently.

    Empty pool returns ``[]``; the calling handler maps to
    ``skip_reason='no_candidates'``."""
    if not isinstance(pool_spec, str) or ":" not in pool_spec:
        return []

    kind, rest = pool_spec.split(":", 1)
    kind = kind.strip().lower()
    rest = rest.strip()

    if kind == "users":
        out: list[uuid.UUID] = []
        for tok in rest.split(","):
            try:
                out.append(uuid.UUID(tok.strip()))
            except (ValueError, TypeError):
                continue
        return out

    if kind == "role":
        from src.app.core.permissions.models import Role
        from src.app.core.users.models import OrganizationMember, User

        # role_id by name, then active members in that role +
        # active org membership.
        role_row = (
            await session.execute(
                select(Role.id).where(
                    Role.organization_id == org_id,
                    Role.name == rest,
                )
            )
        ).scalar_one_or_none()
        if role_row is None:
            return []

        rows = (
            (
                await session.execute(
                    select(User.legacy_uuid)
                    .join(
                        OrganizationMember,
                        OrganizationMember.user_member_id == User.id,
                    )
                    .where(
                        OrganizationMember.organization_id == org_id,
                        OrganizationMember.role_id == role_row,
                        OrganizationMember.is_active.is_(True),
                    )
                    .order_by(User.legacy_uuid.asc())
                )
            )
            .scalars()
            .all()
        )
        return [row for row in rows if isinstance(row, uuid.UUID)]

    # Unknown kind — empty pool.
    return []


# --- Round-robin pointer state ------------------------------------------


async def _bump_routing_pointer(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    pool_spec: str,
    candidates: list[uuid.UUID],
) -> uuid.UUID:
    """Advance the per-pool pointer atomically + return the picked
    user. Acquires a row-level lock on ``tbl_org_settings`` so two
    concurrent workflow firings can't double-pick or skip.

    The pointer state shape on the JSONB column::

        {
          "role:Sales": {
            "last_picked_user_id": "<uuid>",
            "last_picked_at": "<iso8601>"
          },
          ...
        }

    The picker reads the last_picked_user_id, finds its position in
    ``candidates`` (sorted by UUID for deterministic ordering), then
    picks the NEXT one with wrap-around. When the last user isn't
    in the current candidate set (rep removed since last fire), we
    start at index 0.
    """
    from src.app.core.settings.models import OrgSettings

    if not candidates:
        # Defensive — caller should have early-returned.
        raise ValueError("round-robin called with empty candidate list")

    sorted_candidates = sorted(candidates, key=lambda u: str(u))

    stmt = select(OrgSettings).where(OrgSettings.org_id == org_id).with_for_update()
    settings = (await session.execute(stmt)).scalar_one_or_none()

    if settings is None:
        # No settings row exists yet — create one. Org provisioning
        # normally creates this; if it didn't, we make the bare
        # minimum here so routing works.
        settings = OrgSettings(org_id=org_id, routing_state={})
        session.add(settings)
        await session.flush()

    routing_state = dict(settings.routing_state or {})
    pool_state = routing_state.get(pool_spec) or {}
    last_picked_raw = pool_state.get("last_picked_user_id")
    last_picked = _coerce_uuid(last_picked_raw) if last_picked_raw else None

    next_index = 0
    if last_picked is not None and last_picked in sorted_candidates:
        prev_index = sorted_candidates.index(last_picked)
        next_index = (prev_index + 1) % len(sorted_candidates)

    picked = sorted_candidates[next_index]

    routing_state[pool_spec] = {
        "last_picked_user_id": str(picked),
        "last_picked_at": datetime.now(UTC).isoformat(),
    }
    settings.routing_state = routing_state
    await session.commit()
    await session.refresh(settings)
    return picked


def _coerce_uuid(raw: Any) -> uuid.UUID | None:
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


# --- least_loaded --------------------------------------------------------


async def _pick_least_loaded(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    candidates: list[uuid.UUID],
) -> uuid.UUID | None:
    """Return the candidate user with the fewest open leads
    (``status='active'``). Ties broken by max(``last_activity_at``)
    ascending so the rep idle the longest wins. Returns None on
    empty candidate list."""
    if not candidates:
        return None

    from sqlalchemy import func

    from src.app.core.leads.models import Lead, LeadStatus

    rows = (
        await session.execute(
            select(
                Lead.assigned_to_id,
                func.count(Lead.id).label("open_count"),
                func.coalesce(
                    func.max(Lead.last_activity_at),
                    func.max(Lead.created_at),
                ).label("most_recent_touch"),
            )
            .where(Lead.org_id == org_id)
            .where(Lead.assigned_to_id.in_(candidates))
            .where(Lead.status == LeadStatus.active)
            .group_by(Lead.assigned_to_id)
        )
    ).all()

    # Build {user_id: (open_count, most_recent_touch)}.
    stats: dict[uuid.UUID, tuple[int, datetime | None]] = {}
    for user_id, count, touch in rows:
        stats[user_id] = (int(count), touch)

    # Candidates without any open leads get a count of 0 + None
    # last-touch (i.e. effectively "infinitely idle" so they sort
    # FIRST in the tie-break).
    for user_id in candidates:
        if user_id not in stats:
            stats[user_id] = (0, None)

    def _sort_key(item):
        user_id, (count, touch) = item
        # Lower count wins. Within same count, earlier touch wins
        # (so users idle for longer get picked first). None touch
        # sorts before any timestamp.
        return (count, touch is not None, touch or datetime.min, str(user_id))

    sorted_items = sorted(stats.items(), key=_sort_key)
    return sorted_items[0][0]


# --- Assignment via origin services -------------------------------------


async def _assign_to_user(
    session: AsyncSession,
    *,
    run,
    target: str,
    user_id: uuid.UUID,
    method: str,
) -> tuple[str | None, str | None]:
    """Apply the assignment via leads.reassign_lead / contacts.reassign_contact.
    Returns ``(skip_reason, error_msg)`` — both None on success."""
    actor_user_id = getattr(run, "created_by_user_id", None) or user_id
    note = f"Auto-routed by workflow ({method})"

    try:
        if target == "lead.assigned_to_id":
            from src.app.core.leads import service as leads_service

            lead_id = getattr(run, "_routing_lead_id", None)
            if lead_id is None:
                return "target_not_found", "no lead_id available"
            await leads_service.reassign_lead(
                session,
                lead_id=lead_id,
                org_id=run.org_id,
                assigned_to_id=user_id,
                note=note,
                actor_user_id=actor_user_id,
            )
            return None, None
        if target == "contact.assigned_to_id":
            from src.app.core.contacts import service as contacts_service

            contact_id = getattr(run, "contact_id", None)
            if contact_id is None:
                return "target_not_found", "no contact_id available"
            await contacts_service.reassign_contact(
                session,
                contact_id=contact_id,
                org_id=run.org_id,
                assigned_to_id=user_id,
                note=note,
                actor_user_id=actor_user_id,
            )
            return None, None
        return "validation_failed", f"unknown target '{target}'"
    except HTTPException as exc:
        if exc.status_code in (401, 403):
            return "permission_denied", str(exc.detail)
        if exc.status_code == 404:
            return "target_not_found", str(exc.detail)
        return "validation_failed", str(exc.detail)
    except Exception as exc:
        return "validation_failed", str(exc)


def _resolve_target_lead_id(
    *, run, node: dict[str, Any], context: dict[str, Any]
) -> uuid.UUID | None:
    """Lift the lead_id off the trigger payload or node config so
    ``_assign_to_user`` can fire ``reassign_lead`` against it.
    Mirrors the helper in :mod:`core.workflows.actions.records`."""
    cfg = node.get("config") or {}
    explicit = cfg.get("lead_id")
    if explicit:
        return _coerce_uuid(explicit)
    payload = context.get("trigger_payload") or {}
    direct = payload.get("lead_id")
    if direct:
        return _coerce_uuid(direct)
    lead = payload.get("lead")
    if isinstance(lead, dict):
        return _coerce_uuid(lead.get("id"))
    return None


def _stash_lead_id(run, lead_id: uuid.UUID | None) -> None:
    """The reassign helper reads ``run._routing_lead_id`` to know
    which lead row to mutate. We attach it as a transient attribute
    so we don't have to thread it through every helper signature."""
    run._routing_lead_id = lead_id


def _normalise_target(target: Any) -> str:
    """Accept the spec's literal ``"lead.owner_user_id"`` /
    ``"contact.owner_user_id"`` strings + map to the actual column
    names (``assigned_to_id`` on both Lead and Contact)."""
    if not isinstance(target, str):
        return "lead.assigned_to_id"
    if target in ("lead.owner_user_id", "lead.assigned_to_id"):
        return "lead.assigned_to_id"
    if target in ("contact.owner_user_id", "contact.assigned_to_id"):
        return "contact.assigned_to_id"
    return target


# --- routing.round_robin ------------------------------------------------


async def _round_robin(session, *, run, step_run, node, context):
    cfg = node.get("config") or {}
    pool_spec = cfg.get("pool")
    target = _normalise_target(cfg.get("target", "lead.assigned_to_id"))

    if not isinstance(pool_spec, str) or not pool_spec:
        return _result_skipped("validation_failed", reason="missing_pool")

    candidates = await _resolve_pool(session, org_id=run.org_id, pool_spec=pool_spec)
    if not candidates:
        return _result_skipped("no_candidates", pool=pool_spec, pool_size=0)

    picked = await _bump_routing_pointer(
        session, org_id=run.org_id, pool_spec=pool_spec, candidates=candidates
    )
    if target.startswith("lead."):
        _stash_lead_id(run, _resolve_target_lead_id(run=run, node=node, context=context))
    reason, msg = await _assign_to_user(
        session, run=run, target=target, user_id=picked, method="round_robin"
    )
    if reason is not None:
        return _result_skipped(reason, error=msg)

    return _result_assigned(
        assigned_user_id=picked,
        method="round_robin",
        pool_size=len(candidates),
    )


# --- routing.least_loaded -----------------------------------------------


async def _least_loaded(session, *, run, step_run, node, context):
    cfg = node.get("config") or {}
    pool_spec = cfg.get("pool")
    target = _normalise_target(cfg.get("target", "lead.assigned_to_id"))

    if not isinstance(pool_spec, str) or not pool_spec:
        return _result_skipped("validation_failed", reason="missing_pool")

    candidates = await _resolve_pool(session, org_id=run.org_id, pool_spec=pool_spec)
    if not candidates:
        return _result_skipped("no_candidates", pool=pool_spec, pool_size=0)

    picked = await _pick_least_loaded(session, org_id=run.org_id, candidates=candidates)
    if picked is None:
        return _result_skipped("no_candidates", pool=pool_spec)

    if target.startswith("lead."):
        _stash_lead_id(run, _resolve_target_lead_id(run=run, node=node, context=context))
    reason, msg = await _assign_to_user(
        session, run=run, target=target, user_id=picked, method="least_loaded"
    )
    if reason is not None:
        return _result_skipped(reason, error=msg)

    return _result_assigned(
        assigned_user_id=picked,
        method="least_loaded",
        pool_size=len(candidates),
    )


# --- routing.territory --------------------------------------------------


async def _territory(session, *, run, step_run, node, context):
    """Pick a user whose configured territories include the lead's
    region/state/city field. Inline territory_map in node config so
    we don't depend on a user-metadata column the schema doesn't
    yet have."""
    cfg = node.get("config") or {}
    territory_map = cfg.get("territory_map") or {}
    match_field = cfg.get("match_field", "region")
    target = _normalise_target(cfg.get("target", "lead.assigned_to_id"))

    if not isinstance(territory_map, dict) or not territory_map:
        return await _fallback_route(
            session, run=run, step_run=step_run, node=node, context=context
        )

    # Read the lead's field value from the trigger payload's `lead`
    # snapshot. Falls back to context's contact snapshot when
    # routing on contact-level territories.
    payload = context.get("trigger_payload") or {}
    lead = payload.get("lead") or {}
    value = None
    if isinstance(lead, dict):
        value = lead.get(match_field)
    if value is None:
        contact = context.get("contact") or {}
        if isinstance(contact, dict):
            value = contact.get(match_field)
    if not isinstance(value, str) or not value:
        return await _fallback_route(
            session, run=run, step_run=step_run, node=node, context=context
        )

    value_lower = value.lower()
    matching: list[uuid.UUID] = []
    for user_id_str, territories in territory_map.items():
        if not isinstance(territories, list):
            continue
        if any(isinstance(t, str) and t.lower() == value_lower for t in territories):
            user_uuid = _coerce_uuid(user_id_str)
            if user_uuid is not None:
                matching.append(user_uuid)

    if not matching:
        return await _fallback_route(
            session, run=run, step_run=step_run, node=node, context=context
        )

    # When multiple users match the territory, pick the least-loaded
    # among them so a busy rep doesn't grab every Mumbai lead.
    picked = await _pick_least_loaded(session, org_id=run.org_id, candidates=matching)
    if picked is None:
        return _result_skipped("no_candidates", pool_size=len(matching))

    if target.startswith("lead."):
        _stash_lead_id(run, _resolve_target_lead_id(run=run, node=node, context=context))
    reason, msg = await _assign_to_user(
        session, run=run, target=target, user_id=picked, method="territory"
    )
    if reason is not None:
        return _result_skipped(reason, error=msg)

    return _result_assigned(
        assigned_user_id=picked,
        method="territory",
        pool_size=len(matching),
    )


# --- routing.skill ------------------------------------------------------


async def _skill(session, *, run, step_run, node, context):
    """Pick a user whose configured skills include the lead's
    skill-required value. Same inline-map shape as territory."""
    cfg = node.get("config") or {}
    skill_map = cfg.get("skill_map") or {}
    match_field = cfg.get("match_field", "skill_required")
    target = _normalise_target(cfg.get("target", "lead.assigned_to_id"))

    if not isinstance(skill_map, dict) or not skill_map:
        return await _fallback_route(
            session, run=run, step_run=step_run, node=node, context=context
        )

    payload = context.get("trigger_payload") or {}
    lead = payload.get("lead") or {}
    value = lead.get(match_field) if isinstance(lead, dict) else None
    if value is None:
        # Try custom_data.<key> too — operators often store
        # skill-required as a custom field on the lead.
        if isinstance(lead, dict):
            custom = lead.get("custom_data") or {}
            if isinstance(custom, dict):
                value = custom.get(match_field)
    if not isinstance(value, str) or not value:
        return await _fallback_route(
            session, run=run, step_run=step_run, node=node, context=context
        )

    value_lower = value.lower()
    matching: list[uuid.UUID] = []
    for user_id_str, skills in skill_map.items():
        if not isinstance(skills, list):
            continue
        if any(isinstance(s, str) and s.lower() == value_lower for s in skills):
            user_uuid = _coerce_uuid(user_id_str)
            if user_uuid is not None:
                matching.append(user_uuid)

    if not matching:
        return await _fallback_route(
            session, run=run, step_run=step_run, node=node, context=context
        )

    picked = await _pick_least_loaded(session, org_id=run.org_id, candidates=matching)
    if picked is None:
        return _result_skipped("no_candidates", pool_size=len(matching))

    if target.startswith("lead."):
        _stash_lead_id(run, _resolve_target_lead_id(run=run, node=node, context=context))
    reason, msg = await _assign_to_user(
        session, run=run, target=target, user_id=picked, method="skill"
    )
    if reason is not None:
        return _result_skipped(reason, error=msg)

    return _result_assigned(
        assigned_user_id=picked,
        method="skill",
        pool_size=len(matching),
    )


# --- routing.specific_user ---------------------------------------------


async def _specific_user(session, *, run, step_run, node, context):
    cfg = node.get("config") or {}
    target = _normalise_target(cfg.get("target", "lead.assigned_to_id"))
    user_id = _coerce_uuid(cfg.get("user_id"))
    if user_id is None:
        return _result_skipped("validation_failed", reason="missing_user_id")

    if target.startswith("lead."):
        _stash_lead_id(run, _resolve_target_lead_id(run=run, node=node, context=context))
    reason, msg = await _assign_to_user(
        session, run=run, target=target, user_id=user_id, method="specific_user"
    )
    if reason is not None:
        return _result_skipped(reason, error=msg)

    return _result_assigned(assigned_user_id=user_id, method="specific_user", pool_size=1)


# --- Fallback driver ---------------------------------------------------


async def _fallback_route(session, *, run, step_run, node, context):
    """Used by territory + skill when no user matches. Reads
    ``config.fallback`` (default ``round_robin``) and re-dispatches
    through the matching handler."""
    cfg = node.get("config") or {}
    fallback = cfg.get("fallback", "round_robin")
    if fallback == "round_robin":
        return await _round_robin(session, run=run, step_run=step_run, node=node, context=context)
    if fallback == "least_loaded":
        return await _least_loaded(session, run=run, step_run=step_run, node=node, context=context)
    if fallback == "specific_user":
        return await _specific_user(session, run=run, step_run=step_run, node=node, context=context)
    return _result_skipped("no_candidates", reason="no_fallback_match")


# --- Registration ------------------------------------------------------


def register() -> None:
    register_action("routing.round_robin", lambda: _round_robin)
    register_action("routing.least_loaded", lambda: _least_loaded)
    register_action("routing.territory", lambda: _territory)
    register_action("routing.skill", lambda: _skill)
    register_action("routing.specific_user", lambda: _specific_user)


register()


__all__ = ["register"]
