"""Centralised lead-ingestion service shared by all five channels.

Every inbound lead — manual, bulk-import, embeddable widget, Google
Ads webhook, Meta Ads webhook — flows through `ingest()`. The
benefit: dedup logic and routing assignment are defined once, not
five times, so behaviour stays consistent regardless of where the
lead arrived from.

The function takes one of two contact-shape inputs:

  - `contact_id` — caller has already resolved the contact (manual
    POST /leads, which takes a contact_id; the four other channels
    also use this path after running their own find-or-create).
  - `contact_payload` — caller wants ingest to find-or-create the
    contact via phone/email dedup. Used as a future-proof
    alternative; v1 callers all pre-resolve via the channel's own
    dedup loop because they need the contact id for their per-channel
    audit/log rows anyway.

Outcomes:

  - `IngestResult(action="created", lead_id=…, contact_id=…,
    assignee_id=…)` — fresh lead, picked an assignee (or None if no
    eligible user).
  - `IngestResult(action="merged", lead_id=…, contact_id=…,
    assignee_id=existing.assigned_to_id)` — found an OPEN lead for
    the contact; appended a "Touchpoint via {source}" activity and
    returned the existing lead's id.

The `merged` outcome NEVER reassigns the open lead. The original
rep keeps ownership; only an extra timeline entry is added.
`integration.lead.merged_via_dedup` audit event fires so an operator
can grep for high-merge-rate sources (a sign of repeat customers).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.activities.models import ActivityType
from src.app.core.activities.service import log as activities_log
from src.app.core.leads.dedup import find_open_lead_for_contact
from src.app.core.leads.models import LeadSource
from src.app.core.leads.routing import pick_assignee
from src.app.core.leads.schemas import LeadCreate
from src.app.core.leads.service import create_lead

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Return shape from `ingest()`. `action` tells the caller which
    branch fired so the per-channel response code / log message can
    differ (e.g. embed submission returns 200+`merged` vs 201+`created`)."""

    action: Literal["created", "merged"]
    lead_id: uuid.UUID
    contact_id: uuid.UUID
    assignee_id: uuid.UUID | None


async def ingest(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    source: LeadSource,
    contact_id: uuid.UUID,
    lead_payload: LeadCreate,
    actor_user_id: uuid.UUID | None = None,
) -> IngestResult:
    """Resolve dedup + routing for one inbound lead.

    `lead_payload` is the channel-built `LeadCreate` minus the
    `assigned_to_id` (we set it from `pick_assignee`). The caller's
    `contact_id`, `source`, and `attribution` (already on
    `lead_payload`) take precedence over anything in the payload's
    own contact_id field — defence against caller mistakes.

    `require_all_required` is forced False — all five ingestion paths
    accept partial data (the submitter can't know the org's required
    custom-field shape). Staff fill in blanks via the edit form.
    """
    # 1. Dedup against an open lead for the resolved contact.
    existing_lead_id = await find_open_lead_for_contact(
        session, org_id=org_id, contact_id=contact_id
    )
    existing_assignee_id: uuid.UUID | None = None
    if existing_lead_id is not None:
        # Surface the existing lead's current owner in `IngestResult`
        # so `assigned` publishers / notifiers on the merged branch
        # don't get `None` when the row is actually owned. The
        # additional round-trip is cheap (single-PK read) and only
        # fires on the dedup-hit path.
        from src.app.core.leads.models import Lead as _Lead
        from sqlalchemy import select as _select

        _existing = (
            await session.execute(
                _select(_Lead.assigned_to_id).where(_Lead.id == existing_lead_id)
            )
        ).scalar_one_or_none()
        existing_assignee_id = _existing
        # Append a "touchpoint" activity so the open lead's timeline
        # shows the new inbound signal. We use `ActivityType.note`
        # (the existing enum has no dedicated `touchpoint` value) with
        # a payload that lets the UI render it specially when needed.
        await activities_log(
            entity_type="lead",
            entity_id=existing_lead_id,
            type=ActivityType.note,
            payload={
                "kind": "touchpoint",
                "source": source.value,
                "text": f"New touchpoint via {source.value}",
            },
            user_id=actor_user_id,
            org_id=org_id,
        )
        await audit.log(
            "lead.ingested_merged_to_existing",
            entity_type="lead",
            entity_id=existing_lead_id,
            after={
                "source": source.value,
                "contact_id": str(contact_id),
            },
        )
        return IngestResult(
            action="merged",
            lead_id=existing_lead_id,
            contact_id=contact_id,
            assignee_id=existing_assignee_id,
        )

    # 2. Fresh lead — pick an assignee, then create.
    # Any authenticated caller (JWT user) who creates a lead through
    # the app owns that lead, regardless of the `source` label they
    # picked in the "Add Lead" modal. Manual, WhatsApp Flow,
    # Referral, Ad — if a signed-in operator hit the "Add Lead"
    # button, they're the owner. This closes the "I created a lead
    # and it landed as Unassigned" surprise where a rep picks
    # ``source=whatsapp_flow`` in the modal and the lead falls back
    # to round-robin.
    #
    # Public / server-to-server paths that lack an ``actor_user_id``
    # (embed widget, ad-form webhooks, bulk imports, workflow
    # ingest) still go through round-robin so no single rep drowns
    # in cold inbound.
    if actor_user_id is not None:
        assignee_id: uuid.UUID | None = actor_user_id
    else:
        assignee_id = await pick_assignee(session, org_id=org_id, source=source.value)
    # Rebuild the payload so source / contact_id / assignee come from
    # ingest's arguments, not whatever the caller put on the payload.
    # `model_copy(update=...)` is the Pydantic v2 idiom.
    final_payload = lead_payload.model_copy(
        update={
            "contact_id": contact_id,
            "source": source,
            "assigned_to_id": assignee_id,
        }
    )
    lead = await create_lead(
        session,
        org_id=org_id,
        payload=final_payload,
        require_all_required=False,
    )
    return IngestResult(
        action="created",
        lead_id=lead.id,
        contact_id=contact_id,
        assignee_id=assignee_id,
    )


__all__ = ["IngestResult", "ingest"]
