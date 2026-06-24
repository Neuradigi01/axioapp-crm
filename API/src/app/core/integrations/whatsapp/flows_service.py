"""WhatsApp Flows service
(whatsapp-platform-upgrade Step 25).

Single choke-point for Meta Flows + the auto-action dispatcher that
runs on every inbound ``nfm_reply`` submission. Six public entry
points:

  * :func:`load_template`           — bundled JSON template loader.
  * :func:`publish_flow`            — POST Meta create → asset upload → publish.
  * :func:`delete_flow`             — DELETE Meta flow (deprecate).
  * :func:`test_send_flow`          — ship a one-off flow to a phone.
  * :func:`record_submission`       — persist ``nfm_reply`` + run the
    category-specific auto-action.
  * :func:`available_templates`     — list of bundled templates for
    the SPA template picker.

Auto-action dispatch
--------------------

Per the step spec:

  * ``appointment_booking`` → calls
    :func:`appointments.service.create_appointment` with the
    submitted date/time/service + a round-robin assignee.
  * ``lead_capture`` → calls :func:`leads.ingest.ingest` with
    ``source=LeadSource.whatsapp_flow``.
  * ``feedback`` → writes a row into ``tbl_reviews`` with
    ``source='whatsapp_flow'``.
  * ``signup`` / ``custom`` → no auto-action; the submission row
    stands alone for the operator to triage.

Every dispatch is best-effort. Failures are logged + the
submission row is still persisted with ``action_taken='failed'``;
the operator can rerun the action manually from the SPA submissions
table (future Step 26+ surface). The webhook handler must never
fail because a downstream service balked.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.integrations.crypto import decrypt
from src.app.core.integrations.meta.api_client import MetaGraphClient
from src.app.core.integrations.whatsapp.connect import get_active_config
from src.app.core.integrations.whatsapp.models import (
    WhatsAppFlow,
    WhatsAppFlowSubmission,
)

logger = logging.getLogger(__name__)


_TEMPLATES_DIR = Path(__file__).parent / "flow_templates"


# Templates that ship out of the box. Keys must match the
# `whatsapp_flow_category` ENUM values used in the DB.
_BUILTIN_TEMPLATES: dict[str, str] = {
    "appointment_booking": "appointment_booking.json",
    "lead_capture": "lead_capture.json",
    "feedback": "feedback.json",
}


class FlowsServiceError(RuntimeError):
    """4xx-shaped error raised by the service layer; the router
    translates to HTTPException."""


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------


def load_template(category: str) -> dict[str, Any]:
    """Return the bundled JSON template for the given category.

    Raises :class:`FlowsServiceError` for unknown categories — the
    spec's v1 surface ships three templates only; the ``custom``
    category starts with an empty skeleton."""
    if category == "custom":
        return {
            "version": "5.0",
            "data_api_version": "3.0",
            "routing_model": {"CUSTOM": []},
            "screens": [
                {
                    "id": "CUSTOM",
                    "title": "Custom flow",
                    "terminal": True,
                    "data": {},
                    "layout": {
                        "type": "SingleColumnLayout",
                        "children": [],
                    },
                }
            ],
        }
    filename = _BUILTIN_TEMPLATES.get(category)
    if filename is None:
        raise FlowsServiceError(
            f"unknown flow template {category!r}; must be one of "
            f"{sorted(_BUILTIN_TEMPLATES) + ['custom']}"
        )
    path = _TEMPLATES_DIR / filename
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FlowsServiceError(
            f"could not load template {category!r}: {exc}"
        ) from exc


def available_templates() -> list[dict[str, str]]:
    """List bundled templates for the SPA picker. Returned shape:
    ``[{key, label, description}]`` — the labels live here so we
    keep marketing copy out of the front-end."""
    return [
        {
            "key": "appointment_booking",
            "label": "Appointment booking",
            "description": (
                "Date + time + service picker. Auto-creates an "
                "appointment in your CRM on submit."
            ),
        },
        {
            "key": "lead_capture",
            "label": "Lead capture",
            "description": (
                "Name + interest + budget intake. Auto-creates a "
                "lead and routes to a sales rep."
            ),
        },
        {
            "key": "feedback",
            "label": "Customer feedback",
            "description": (
                "Star rating + topic + comments. Lands in your "
                "Reviews inbox tagged 'whatsapp_flow'."
            ),
        },
        {
            "key": "custom",
            "label": "Blank custom",
            "description": (
                "Empty single-screen flow. Edit the JSON to your "
                "needs — no auto-action wired."
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Meta Graph calls
# ---------------------------------------------------------------------------


async def _resolve_meta_client(
    session: AsyncSession,
) -> tuple[MetaGraphClient, str, Any]:
    """Resolve the active WhatsApp integration + a Graph client.

    Returns ``(client, waba_id, config)``. Raises
    :class:`FlowsServiceError` when the org has no connected
    WhatsApp config — the router surfaces as 409."""
    from src.app.core.integrations.models import (
        Integration,
        IntegrationProvider,
        IntegrationStatus,
    )

    bundle = await get_active_config(session)
    if bundle is None:
        raise FlowsServiceError(
            "WhatsApp is not connected — connect it from Integrations first."
        )
    _, wa_config = bundle
    if not wa_config.waba_id:
        raise FlowsServiceError(
            "WhatsApp integration is missing a WABA id."
        )

    # Flow operations use the same OAuth-issued user token the rest
    # of the Graph calls do — pulled from the `whatsapp` integration
    # row, not the `meta_ads` row (Step 24's ads_lookup uses that).
    integration = (
        await session.execute(
            select(Integration).where(
                Integration.org_id == wa_config.org_id,
                Integration.provider == IntegrationProvider.whatsapp,
                Integration.status == IntegrationStatus.connected,
            )
        )
    ).scalar_one_or_none()
    if integration is None:
        raise FlowsServiceError(
            "no connected WhatsApp integration row for this org."
        )

    client = MetaGraphClient(integration=integration, session=session)
    return client, wa_config.waba_id, wa_config


async def publish_flow(
    session: AsyncSession, *, flow: WhatsAppFlow
) -> WhatsAppFlow:
    """Create the Flow at Meta (if not already), upload the JSON
    asset, then publish. Idempotent — re-publishing an already-
    published flow updates the JSON assets in place and bumps
    the Meta-side version. Updates the local row with
    ``meta_flow_id`` + ``status='published'`` on success.

    Best-effort exceptions are not the right contract here — a
    publish failure is operator-visible (they pressed the button
    and want to know what happened). We bubble the
    :class:`FlowsServiceError` so the router can render a friendly
    400/409."""
    client, waba_id, _ = await _resolve_meta_client(session)
    try:
        if not flow.meta_flow_id:
            created = await client.post(
                f"/{waba_id}/flows",
                params={
                    "name": flow.name,
                    "categories": json.dumps([flow.category.upper()]),
                },
            )
            meta_id = str(created.get("id") or "")
            if not meta_id:
                raise FlowsServiceError(
                    "Meta did not return a flow id on create."
                )
            flow.meta_flow_id = meta_id
            await session.commit()
            await session.refresh(flow)

        # Asset upload — Meta expects the JSON as a `flow.json`
        # asset on the flow.
        await client.post(
            f"/{flow.meta_flow_id}/assets",
            params={
                "name": "flow.json",
                "asset_type": "FLOW_JSON",
                "file": json.dumps(flow.json_definition),
            },
        )
        # Publish — once published, the flow can be sent via
        # interactive messages of type=flow.
        await client.post(f"/{flow.meta_flow_id}/publish")
    except FlowsServiceError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "publish_flow failed for flow %s (meta=%s)",
            flow.id,
            flow.meta_flow_id,
        )
        raise FlowsServiceError(
            f"Meta rejected the publish call: {exc}"
        ) from exc

    flow.status = "published"
    flow.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(flow)
    await audit.log(
        "whatsapp.flows.published",
        entity_type="whatsapp_flow",
        entity_id=flow.id,
        after={"meta_flow_id": flow.meta_flow_id},
    )
    return flow


async def delete_flow(
    session: AsyncSession, *, flow: WhatsAppFlow
) -> None:
    """Soft-deprecate a flow: archive locally + DELETE on Meta when
    a meta_flow_id is known. We don't drop the local row so the
    submissions history stays intact (the FK is ``ON DELETE SET
    NULL``)."""
    if flow.meta_flow_id:
        try:
            client, _, _ = await _resolve_meta_client(session)
            await client.delete(f"/{flow.meta_flow_id}")
        except Exception:  # noqa: BLE001
            logger.exception(
                "delete_flow: Meta delete failed for flow %s (meta=%s) — "
                "archiving locally regardless",
                flow.id,
                flow.meta_flow_id,
            )
    flow.status = "archived"
    flow.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await audit.log(
        "whatsapp.flows.archived",
        entity_type="whatsapp_flow",
        entity_id=flow.id,
        before={"meta_flow_id": flow.meta_flow_id},
    )


async def test_send_flow(
    session: AsyncSession,
    *,
    flow: WhatsAppFlow,
    to_phone: str,
) -> dict[str, Any]:
    """Send the flow as an interactive message to ``to_phone`` for
    smoke-testing. Only published flows can be sent — raise on
    drafts. We POST directly to Meta's send endpoint rather than
    going through ``WhatsAppAdapter.send`` because flows use a
    different envelope shape and the adapter is intentionally
    scoped to text / media / interactive(buttons/cta/list)."""
    if flow.status != "published":
        raise FlowsServiceError(
            "Only published flows can be test-sent. "
            "Publish the flow first."
        )
    if not flow.meta_flow_id:
        raise FlowsServiceError(
            "Flow is missing the Meta-side id — re-publish and retry."
        )
    client, _, wa_config = await _resolve_meta_client(session)
    token = (
        decrypt(wa_config.access_token_enc)
        if wa_config.access_token_enc
        else None
    )
    envelope = {
        "messaging_product": "whatsapp",
        "to": "".join(c for c in to_phone if c.isdigit()),
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "body": {"text": f"Test send — {flow.name}"},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_token": str(flow.id),
                    "flow_id": flow.meta_flow_id,
                    "flow_cta": "Open form",
                    "flow_action": "navigate",
                },
            },
        },
    }
    try:
        response = await client.post(
            f"/{wa_config.phone_id}/messages",
            params=envelope,
            access_token=token,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "test_send_flow: Meta send failed for flow %s", flow.id
        )
        raise FlowsServiceError(
            f"Meta rejected the test send: {exc}"
        ) from exc
    await audit.log(
        "whatsapp.flows.test_sent",
        entity_type="whatsapp_flow",
        entity_id=flow.id,
        after={"to_phone": to_phone, "meta_response": response},
    )
    return response


# ---------------------------------------------------------------------------
# Submission auto-action dispatch
# ---------------------------------------------------------------------------


async def record_submission(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    flow_token: Optional[str],
    contact_id: Optional[uuid.UUID],
    conversation_id: Optional[uuid.UUID],
    response_data: dict[str, Any],
) -> WhatsAppFlowSubmission:
    """Persist a flow submission + dispatch the category-specific
    auto-action.

    ``flow_token`` is whatever Meta echoed back from the original
    interactive-flow send (we set it to ``str(flow.id)`` in
    :func:`test_send_flow`); we use it to resolve the local
    ``WhatsAppFlow`` row, which in turn tells us which auto-action
    to run."""
    flow: WhatsAppFlow | None = None
    if flow_token:
        try:
            token_uuid = uuid.UUID(str(flow_token))
        except (TypeError, ValueError):
            token_uuid = None
        if token_uuid is not None:
            flow = (
                await session.execute(
                    select(WhatsAppFlow).where(
                        WhatsAppFlow.id == token_uuid
                    )
                )
            ).scalar_one_or_none()

    submission = WhatsAppFlowSubmission(
        org_id=org_id,
        flow_id=flow.id if flow else None,
        flow_token=flow_token,
        contact_id=contact_id,
        conversation_id=conversation_id,
        response_data=response_data,
    )
    session.add(submission)
    await session.commit()
    await session.refresh(submission)

    # Run the per-category auto-action. Each branch is independently
    # try/excepted so a bad payload doesn't roll back the submission
    # row — DPDP-style: keep the receipt, even if the downstream
    # action fails. Operators can re-trigger from the UI.
    if flow is not None and contact_id is not None:
        try:
            action_taken, entity_id = await _dispatch_auto_action(
                session,
                flow=flow,
                org_id=org_id,
                contact_id=contact_id,
                response_data=response_data,
            )
            submission.action_taken = action_taken
            submission.action_entity_id = entity_id
            await session.commit()
        except Exception:  # noqa: BLE001
            logger.exception(
                "flow submission auto-action failed for submission=%s flow=%s",
                submission.id,
                flow.id,
            )
            submission.action_taken = "failed"
            await session.commit()

    await audit.log(
        "whatsapp.flows.submission_received",
        entity_type="whatsapp_flow_submission",
        entity_id=submission.id,
        after={
            "flow_id": str(flow.id) if flow else None,
            "category": flow.category if flow else None,
            "action_taken": submission.action_taken,
        },
    )
    return submission


async def _dispatch_auto_action(
    session: AsyncSession,
    *,
    flow: WhatsAppFlow,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    response_data: dict[str, Any],
) -> tuple[str, Optional[uuid.UUID]]:
    """Run the category-specific auto-action. Returns ``(action,
    entity_id)`` so the submission row can record what produced
    what. Unknown categories no-op with ``('none', None)``."""
    category = flow.category

    if category == "lead_capture":
        from src.app.core.leads.ingest import ingest
        from src.app.core.leads.models import LeadSource
        from src.app.core.leads.schemas import LeadCreate

        attribution = {
            "channel": "whatsapp_flow",
            "flow_id": str(flow.id),
            "flow_name": flow.name,
            "raw": response_data,
        }
        # The leads.ingest helper does dedup + routing + assignment;
        # we hand it the contact + the lead-creation payload. The
        # `interest` field from the lead_capture template becomes a
        # tag if the operator wired one, but here we just attach it
        # to `attribution` for downstream filters.
        result = await ingest(
            session,
            org_id=org_id,
            source=LeadSource.whatsapp_flow,
            contact_id=contact_id,
            lead_payload=LeadCreate(
                contact_id=contact_id,
                source=LeadSource.whatsapp_flow,
                attribution=attribution,
                custom_data={
                    "interest": response_data.get("interest"),
                    "budget": response_data.get("budget"),
                    "notes": response_data.get("notes"),
                },
            ),
            actor_user_id=None,
        )
        return "lead_created", result.lead_id

    if category == "appointment_booking":
        from src.app.core.appointments.schemas import AppointmentCreate
        from src.app.core.appointments.service import create_appointment
        from src.app.core.leads.routing import pick_assignee

        assignee = await pick_assignee(
            session, org_id=org_id, source="whatsapp_flow"
        )
        if assignee is None:
            logger.info(
                "appointment auto-action skipped — no assignee available"
            )
            return "skipped_no_assignee", None
        scheduled_at = _parse_scheduled_at(response_data)
        if scheduled_at is None:
            logger.info(
                "appointment auto-action skipped — could not parse date/time"
            )
            return "skipped_bad_datetime", None
        appt = await create_appointment(
            session,
            org_id=org_id,
            current_user_id=assignee,
            payload=AppointmentCreate(
                contact_id=contact_id,
                title=f"{flow.name} — WhatsApp booking",
                purpose=str(response_data.get("service") or "consultation"),
                scheduled_at=scheduled_at,
                duration_min=30,
                location=None,
                assigned_to_id=assignee,
                custom_data={
                    "source": "whatsapp_flow",
                    "flow_id": str(flow.id),
                    "raw": response_data,
                },
            ),
        )
        return "appointment_created", appt.id

    if category == "feedback":
        from src.app.core.reviews.models import Review, ReviewStatus

        try:
            rating = int(response_data.get("rating") or 0)
        except (TypeError, ValueError):
            rating = 0
        review = Review(
            org_id=org_id,
            source="whatsapp_flow",
            contact_id=contact_id,
            rating=max(1, min(5, rating)) if rating else 3,
            text=str(response_data.get("comment") or "").strip() or None,
            status=ReviewStatus.pending_reply,
            tags=[
                str(response_data.get("topic") or "general")
            ],
        )
        session.add(review)
        await session.commit()
        await session.refresh(review)
        return "review_created", review.id

    # signup / custom — no auto-action by design.
    return "none", None


def _parse_scheduled_at(
    response_data: dict[str, Any],
) -> Optional[datetime]:
    """Build a tz-aware UTC datetime from the appointment template's
    ``preferred_date`` (``YYYY-MM-DD``) + ``preferred_time``
    (``HH:MM``). Returns None when either piece is missing or
    malformed — the dispatcher then skips the auto-action and
    leaves the operator to triage manually."""
    raw_date = str(response_data.get("preferred_date") or "")
    raw_time = str(response_data.get("preferred_time") or "")
    if not raw_date:
        return None
    if not raw_time:
        raw_time = "10:00"
    try:
        return datetime.strptime(
            f"{raw_date} {raw_time}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        # Try ISO-shaped date with no explicit time.
        try:
            return datetime.fromisoformat(raw_date).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return None


__all__ = [
    "FlowsServiceError",
    "available_templates",
    "delete_flow",
    "load_template",
    "publish_flow",
    "record_submission",
    "test_send_flow",
]
