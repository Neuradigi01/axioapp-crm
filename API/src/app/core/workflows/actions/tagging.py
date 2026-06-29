"""Tagging + scoring action handlers — Step 10.

Five handlers register against the action registry:

  * ``tagging.add_tag``        — append a tag (renders variables;
                                idempotent).
  * ``tagging.remove_tag``     — drop a tag (silent on missing).
  * ``tagging.add_to_list``    — placeholder (groups module is
                                filter-based, no manual membership).
  * ``tagging.remove_from_list`` — same placeholder.
  * ``tagging.set_lead_score`` — set / increment / decrement Lead
                                score via leads.service.update_lead.
                                Crossing a configured threshold
                                emits ``lead.score_threshold`` so
                                other workflows can re-trigger.

Tags live on ``tbl_contacts.tags`` (PostgreSQL array). Leads don't
carry a tags column in the current schema, so the ``target='lead'``
config option short-circuits to ``ActionNotImplemented`` — operators
add lead-shaped tags via custom_data instead.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from src.app.core.workflows.actions import register_action
from src.app.core.workflows.exceptions import ActionNotImplemented


logger = logging.getLogger(__name__)


def _result_sent(output: dict[str, Any]):
    from src.app.core.workflows.engine import ActionResult

    return ActionResult(output=output)


def _result_skipped(reason: str, **extra: Any):
    from src.app.core.workflows.engine import ActionResult

    payload: dict[str, Any] = dict(extra) if extra else {}
    payload["skip_reason"] = reason
    return ActionResult(skip_reason=reason, output=payload)


def _render(value: Any, context: dict[str, Any]) -> Any:
    if not isinstance(value, str):
        return value
    from src.app.core.templates.variables import resolve as render_resolve

    return render_resolve(value, context)


def _classify(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, HTTPException):
        code = exc.status_code
        if code in (401, 403):
            return "permission_denied", str(exc.detail)
        if code == 404:
            return "target_not_found", str(exc.detail)
        return "validation_failed", str(exc.detail)
    if isinstance(exc, ValidationError):
        return "validation_failed", str(exc)
    return "validation_failed", str(exc)


def _resolve_contact_id(*, run, node: dict[str, Any], context: dict[str, Any]):
    cfg = node.get("config") or {}
    explicit = cfg.get("contact_id")
    if explicit:
        try:
            return uuid.UUID(str(explicit))
        except (ValueError, TypeError):
            return None
    return getattr(run, "contact_id", None)


def _resolve_lead_id(*, node: dict[str, Any], context: dict[str, Any]):
    cfg = node.get("config") or {}
    explicit = cfg.get("lead_id")
    if explicit:
        try:
            return uuid.UUID(str(explicit))
        except (ValueError, TypeError):
            return None
    payload = context.get("trigger_payload") or {}
    raw = payload.get("lead_id") or (
        payload.get("lead", {}) or {}
    ).get("id")
    if raw is None:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


# --- tagging.add_tag / remove_tag ----------------------------------------


async def _add_tag(session, *, run, step_run, node, context):
    from src.app.core.contacts import service as contacts_service
    from src.app.core.contacts.schemas import ContactUpdate
    from sqlalchemy import select

    from src.app.core.contacts.models import Contact

    cfg = node.get("config") or {}
    target = cfg.get("target", "contact")
    if target != "contact":
        # Lead tagging isn't supported (no Lead.tags column).
        raise ActionNotImplemented(
            "tagging.add_tag",
            f"target='{target}' not supported — Lead has no tags column",
        )

    contact_id = _resolve_contact_id(run=run, node=node, context=context)
    if contact_id is None:
        return _result_skipped("target_not_found", reason="no_contact_id")

    tag = _render(cfg.get("tag"), context)
    if not isinstance(tag, str) or not tag.strip():
        return _result_skipped("validation_failed", reason="empty_tag")

    contact = (
        await session.execute(select(Contact).where(Contact.id == contact_id))
    ).scalar_one_or_none()
    if contact is None:
        return _result_skipped("target_not_found", reason="contact_missing")

    existing = list(contact.tags or [])
    if tag.strip() in existing:
        # Idempotent — no-op.
        return _result_sent(
            {"contact_id": str(contact_id), "tag": tag.strip(), "added": False}
        )
    new_tags = existing + [tag.strip()]
    try:
        await contacts_service.update_contact(
            session,
            contact_id=contact_id,
            payload=ContactUpdate(tags=new_tags),
        )
    except Exception as exc:
        reason, msg = _classify(exc)
        return _result_skipped(reason, error=msg)

    return _result_sent(
        {"contact_id": str(contact_id), "tag": tag.strip(), "added": True}
    )


async def _remove_tag(session, *, run, step_run, node, context):
    from sqlalchemy import select

    from src.app.core.contacts import service as contacts_service
    from src.app.core.contacts.models import Contact
    from src.app.core.contacts.schemas import ContactUpdate

    cfg = node.get("config") or {}
    target = cfg.get("target", "contact")
    if target != "contact":
        raise ActionNotImplemented(
            "tagging.remove_tag",
            f"target='{target}' not supported — Lead has no tags column",
        )

    contact_id = _resolve_contact_id(run=run, node=node, context=context)
    if contact_id is None:
        return _result_skipped("target_not_found", reason="no_contact_id")

    tag = _render(cfg.get("tag"), context)
    if not isinstance(tag, str) or not tag.strip():
        return _result_skipped("validation_failed", reason="empty_tag")

    contact = (
        await session.execute(select(Contact).where(Contact.id == contact_id))
    ).scalar_one_or_none()
    if contact is None:
        return _result_skipped("target_not_found", reason="contact_missing")

    existing = list(contact.tags or [])
    target_tag = tag.strip()
    if target_tag not in existing:
        # Silent — no-op + no error.
        return _result_sent(
            {
                "contact_id": str(contact_id),
                "tag": target_tag,
                "removed": False,
            }
        )
    new_tags = [t for t in existing if t != target_tag]
    try:
        await contacts_service.update_contact(
            session,
            contact_id=contact_id,
            payload=ContactUpdate(tags=new_tags),
        )
    except Exception as exc:
        reason, msg = _classify(exc)
        return _result_skipped(reason, error=msg)

    return _result_sent(
        {
            "contact_id": str(contact_id),
            "tag": target_tag,
            "removed": True,
        }
    )


# --- tagging.set_lead_score ---------------------------------------------


async def _set_lead_score(session, *, run, step_run, node, context):
    from sqlalchemy import select

    from src.app.core.leads import service as leads_service
    from src.app.core.leads.models import Lead
    from src.app.core.leads.schemas import LeadUpdate

    cfg = node.get("config") or {}
    operation = cfg.get("operation", "set")
    value = cfg.get("value")
    if not isinstance(value, (int, float)):
        return _result_skipped("validation_failed", reason="numeric_value_required")
    if operation not in ("set", "increment", "decrement"):
        return _result_skipped(
            "validation_failed", reason=f"unknown_operation:{operation}"
        )

    lead_id = _resolve_lead_id(node=node, context=context)
    if lead_id is None:
        return _result_skipped("target_not_found", reason="no_lead_id")

    lead = (
        await session.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()
    if lead is None:
        return _result_skipped("target_not_found", reason="lead_missing")

    prior_score = int(lead.lead_score or 0)
    if operation == "set":
        new_score = int(value)
    elif operation == "increment":
        new_score = prior_score + int(value)
    else:  # decrement
        new_score = prior_score - int(value)
    # Clamp to [0, 100] per the model's documented bounds.
    new_score = max(0, min(100, new_score))

    if new_score == prior_score:
        return _result_sent(
            {
                "lead_id": str(lead_id),
                "prior_score": prior_score,
                "new_score": new_score,
                "changed": False,
            }
        )

    try:
        await leads_service.update_lead(
            session, lead_id=lead_id, payload=LeadUpdate(lead_score=new_score)
        )
    except ValidationError:
        # LeadUpdate may not expose lead_score directly; fall back to
        # a direct ORM set + commit through the active session.
        lead.lead_score = new_score
        await session.commit()
        await session.refresh(lead)
    except Exception as exc:
        reason, msg = _classify(exc)
        return _result_skipped(reason, error=msg)

    # Threshold check — emit lead.score_threshold when the score
    # crosses an operator-supplied bound (default 75).
    threshold = cfg.get("threshold", 75)
    direction: str | None = None
    if isinstance(threshold, (int, float)):
        if prior_score < threshold <= new_score:
            direction = "up"
        elif prior_score >= threshold > new_score:
            direction = "down"
    if direction is not None:
        try:
            from src.app.core.events.bus import publish as events_publish

            await events_publish(
                "lead.score_threshold",
                {
                    "lead_id": str(lead_id),
                    "contact_id": str(lead.contact_id) if lead.contact_id else None,
                    "threshold": threshold,
                    "direction": direction,
                    "prior_score": prior_score,
                    "new_score": new_score,
                    "lead": {
                        "id": str(lead_id),
                        "score": new_score,
                    },
                },
                org_id=lead.org_id,
                event_id=f"lead_score_threshold:{lead_id}:{threshold}:{direction}",
            )
        except Exception:
            logger.exception(
                "tagging.set_lead_score threshold_publish_failed lead=%s",
                lead_id,
            )

    return _result_sent(
        {
            "lead_id": str(lead_id),
            "prior_score": prior_score,
            "new_score": new_score,
            "changed": True,
            "threshold_crossed": direction,
        }
    )


# --- Placeholders -------------------------------------------------------


async def _add_to_list(session, *, run, step_run, node, context):
    raise ActionNotImplemented(
        "tagging.add_to_list",
        "contacts.groups is filter-based — manual membership not yet supported",
    )


async def _remove_from_list(session, *, run, step_run, node, context):
    raise ActionNotImplemented(
        "tagging.remove_from_list",
        "contacts.groups is filter-based — manual membership not yet supported",
    )


# --- Registration -------------------------------------------------------


def register() -> None:
    register_action("tagging.add_tag", lambda: _add_tag)
    register_action("tagging.remove_tag", lambda: _remove_tag)
    register_action("tagging.add_to_list", lambda: _add_to_list)
    register_action("tagging.remove_from_list", lambda: _remove_from_list)
    register_action("tagging.set_lead_score", lambda: _set_lead_score)


register()


__all__ = ["register"]
