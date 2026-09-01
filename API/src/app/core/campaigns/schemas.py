"""Pydantic v2 schemas for the campaigns module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

from src.app.core.campaigns.models import CampaignMessageStatus, CampaignStatus
from src.app.core.conversations.models import ConversationChannel
from src.app.shared.schemas import ORMModel, PaginatedResponse


class AudienceFilter(BaseModel):
    """Campaign audience target — four mutually-exclusive modes:

      1. **Empty** (`{}`): "Everyone in the org". The default.
      2. **Filter**: any of `q` / `source` / `tag` — same shape as the
         `/contacts` list query. Dynamic resolution at send time.
      3. **Group**: `group_id` references a saved `contact_groups` row
         (Step 3.5.7). Dynamic groups re-resolve at send time; static
         groups send to their frozen member list.
      4. **Explicit**: `contact_ids` is a hand-picked list. Frozen at
         save time — send at dispatch goes to exactly these ids.

    Mixing modes 2/3/4 is rejected at the schema layer — the
    audience builder UI (Step 3.5.9) enforces "one mode at a time"
    via radio toggle, and the backend echoes the same constraint so
    a direct API call can't bypass it."""

    q: str | None = None
    source: str | None = None
    tag: str | None = None
    group_id: uuid.UUID | None = None
    contact_ids: list[uuid.UUID] | None = None

    @model_validator(mode="after")
    def _no_mixed_modes(self) -> AudienceFilter:
        has_filter = bool(self.q or self.source or self.tag)
        has_group = self.group_id is not None
        has_ids = self.contact_ids is not None and len(self.contact_ids) > 0
        active = int(has_filter) + int(has_group) + int(has_ids)
        if active > 1:
            raise ValueError(
                "Use exactly one of: filter fields (q/source/tag), group_id, or contact_ids."
            )
        if self.contact_ids is not None and len(self.contact_ids) == 0:
            raise ValueError("contact_ids must be a non-empty list when set.")
        return self


class TemplateVariableBinding(BaseModel):
    """One `{{n}} → value` binding inside `template_variables`.

    `kind='static'`: `value` is the literal text every recipient sees.
    `kind='field'`:  `value` is a contact-field reference like
                     `full_name`, `phone`, `email`, `custom_data.<key>`.
                     Step 3.5.6 dispatch resolves it per contact.
    """

    kind: Literal["static", "field"]
    value: str = Field(min_length=1, max_length=512)


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    channel: ConversationChannel
    audience_filter: AudienceFilter = Field(default_factory=AudienceFilter)
    template: str | None = Field(default=None, min_length=1, max_length=4096)
    template_id: uuid.UUID | None = None
    template_variables: dict[str, TemplateVariableBinding] | None = None
    schedule_at: datetime | None = None
    # whatsapp-platform-upgrade Step 27b — multi-number per org.
    # NULL falls back to the org default phone; an explicit value
    # pins the dispatcher to that Meta phone-number-id.
    send_from_phone_id: str | None = Field(default=None, max_length=64)
    # whatsapp-platform-upgrade Step 29 — A/B testing knobs. When
    # ``is_ab_test`` is True, the four other A/B fields drive the
    # split + winner decision. When False, every other A/B field
    # is ignored (and the underlying columns stay at server defaults).
    is_ab_test: bool = False
    variant_a_template_id: uuid.UUID | None = None
    variant_b_template_id: uuid.UUID | None = None
    split_ratio: int = Field(default=50, ge=0, le=100)
    winner_metric: Literal["reply_rate", "read_rate", "click_rate"] | None = None
    winner_holdback_hours: int = Field(default=24, ge=1, le=168)
    # Campaigns v1 Step 03 — Email sender identity + subject + preheader.
    # Required-when-Email is enforced by _email_channel_requires_sender_and_subject
    # below; the schema keeps the fields nullable so WhatsApp / SMS / etc
    # campaign creates don't have to send them at all.
    email_account_id: uuid.UUID | None = None
    # Campaigns v1 follow-up (migration 0213) — alternate sender for
    # Email campaigns that dispatch via a verified SMTP identity
    # instead of an OAuth mailbox. Exactly one of email_account_id
    # or smtp_sender_id must be set for Email campaigns; the
    # `_email_channel_requires_sender_and_subject` validator below
    # enforces the invariant and DB CHECK
    # `ck_campaigns_email_exactly_one_sender` mirrors it.
    smtp_sender_id: uuid.UUID | None = None
    sender_name: str | None = Field(default=None, min_length=1, max_length=120)
    reply_to: EmailStr | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=998)
    preheader: str | None = Field(default=None, max_length=200)
    # Campaigns v1 Step 04 — inline HTML body for Email campaigns that
    # don't reference a template. Mutually exclusive with ``template``
    # and ``template_id`` for Email (see the validator below); a WA
    # / SMS / etc campaign that sends this field is a schema error.
    body_html: str | None = Field(default=None, max_length=200_000)

    @model_validator(mode="after")
    def _exactly_one_template_source(self) -> CampaignCreate:
        """Either free-text body, an inline HTML body, or a template —
        exactly one of the three. Mixing them would make dispatch's
        text-vs-template branch (Step 3.5.6) ambiguous.

        Step 29 — A/B campaigns skip this check because they pin
        templates via ``variant_a_template_id`` / ``variant_b_template_id``
        instead of ``template`` / ``template_id``.

        Campaigns v1 Step 04 — ``body_html`` is allowed only for Email
        channels; it counts as a third source alongside ``template``
        and ``template_id``."""
        if self.is_ab_test:
            return self
        if self.body_html is not None and self.channel != ConversationChannel.email:
            raise ValueError(
                "body_html is only valid for email campaigns; "
                f"got channel={self.channel.value}"
            )
        sources = [
            src
            for src, value in (
                ("template", self.template),
                ("template_id", self.template_id),
                ("body_html", self.body_html),
            )
            if value is not None
        ]
        if not sources:
            raise ValueError(
                "Provide 'template' (free text), 'template_id' "
                "(approved template), or 'body_html' (Email only)."
            )
        if len(sources) > 1:
            raise ValueError(
                "Use exactly one of 'template', 'template_id', or 'body_html'; "
                f"got {', '.join(sources)}."
            )
        if self.template_id is not None and self.template_variables is None:
            # No variables for a 0-variable template is fine, but make
            # the field explicitly `{}` so dispatch doesn't see None.
            self.template_variables = {}
        return self

    @model_validator(mode="after")
    def _email_channel_requires_sender_and_subject(self) -> CampaignCreate:
        """Campaigns v1 Step 03 — Email dispatch has no way to compose
        a real message without a sender identity, sender name, and
        subject. Reply-to + preheader stay optional (reply-to falls
        back to the mailbox address; preheader falls back to the
        first ~90 chars of the body). WA / SMS / etc campaigns skip
        the check.

        Sender identity: exactly one of ``email_account_id`` (OAuth
        mailbox — Gmail / Microsoft) or ``smtp_sender_id`` (verified
        SMTP sender) must be set. Zero → 422 "pick a sender"; both →
        422 "pick only one". Non-Email channels must have both NULL
        (schema rejects if either is populated) so no ghost sender
        rows lurk on WhatsApp campaigns.
        """
        if self.channel != ConversationChannel.email:
            if self.email_account_id is not None or self.smtp_sender_id is not None:
                raise ValueError(
                    "Non-Email campaigns must not carry email_account_id or smtp_sender_id."
                )
            return self
        has_oauth = self.email_account_id is not None
        has_smtp = self.smtp_sender_id is not None
        if not has_oauth and not has_smtp:
            raise ValueError(
                "Email campaigns require a sender identity — pass either "
                "email_account_id (OAuth mailbox) or smtp_sender_id (verified SMTP)."
            )
        if has_oauth and has_smtp:
            raise ValueError(
                "Pick only one sender: email_account_id (OAuth) OR smtp_sender_id (SMTP), not both."
            )
        missing = [
            name
            for name, value in {
                "sender_name": self.sender_name,
                "subject": self.subject,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError("Email campaigns require: " + ", ".join(missing))
        return self

    @model_validator(mode="after")
    def _validate_ab_config(self) -> CampaignCreate:
        """Step 29 — A/B campaigns must carry both template ids + a
        distinct pair + a winner metric. The minimum-audience guard
        is enforced at start-campaign time (we don't know the
        audience size until then)."""
        if not self.is_ab_test:
            return self
        if self.variant_a_template_id is None or self.variant_b_template_id is None:
            raise ValueError(
                "A/B campaigns require both variant_a_template_id and variant_b_template_id."
            )
        if self.variant_a_template_id == self.variant_b_template_id:
            raise ValueError("Variant A and B must reference different templates.")
        if self.winner_metric is None:
            raise ValueError(
                "A/B campaigns require a winner_metric (reply_rate / read_rate / click_rate)."
            )
        return self


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    audience_filter: AudienceFilter | None = None
    template: str | None = Field(default=None, min_length=1, max_length=4096)
    template_id: uuid.UUID | None = None
    template_variables: dict[str, TemplateVariableBinding] | None = None
    schedule_at: datetime | None = None
    # Campaigns v1 Step 03 — Email fields can be edited on a Draft
    # Email campaign (the channel itself is immutable post-create; see
    # ``update_campaign`` in service.py). No required-when-Email check
    # here because the create-time validator already enforced the
    # invariant on the row.
    email_account_id: uuid.UUID | None = None
    # Migration 0213 — flip a draft Email campaign between an OAuth
    # mailbox and a verified SMTP sender. update_campaign resolves the
    # exactly-one invariant against the row + patch as a whole.
    smtp_sender_id: uuid.UUID | None = None
    sender_name: str | None = Field(default=None, min_length=1, max_length=120)
    reply_to: EmailStr | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=998)
    preheader: str | None = Field(default=None, max_length=200)
    # Campaigns v1 Step 04 — inline HTML body edits for Email drafts.
    body_html: str | None = Field(default=None, max_length=200_000)


class CampaignOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    channel: ConversationChannel
    audience_filter: dict[str, Any]
    template: str | None
    template_id: uuid.UUID | None
    template_variables: dict[str, Any] | None
    schedule_at: datetime | None
    # Campaigns v1 Step 03 — Email sender identity + subject + preheader.
    # NULL for non-Email campaigns.
    email_account_id: uuid.UUID | None = None
    # Migration 0213 — alternate SMTP sender identity. Exactly one of
    # `email_account_id` / `smtp_sender_id` is populated on Email rows.
    smtp_sender_id: uuid.UUID | None = None
    sender_name: str | None = None
    reply_to: str | None = None
    subject: str | None = None
    preheader: str | None = None
    # Campaigns v1 Step 04 — inline HTML body for Email campaigns
    # that don't reference a template. NULL for template-backed and
    # non-Email campaigns.
    body_html: str | None = None
    # Campaigns v1 Step 07 — how many audience contacts were dropped
    # by the hard-bounce suppression pre-flight. 0 for WA campaigns
    # + Email campaigns whose audience had no bounced contacts.
    excluded_bounced_count: int = 0
    status: CampaignStatus
    created_by_id: uuid.UUID | None
    created_at: datetime


CampaignListResponse = PaginatedResponse[CampaignOut]


class CampaignMessageOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    campaign_id: uuid.UUID
    contact_id: uuid.UUID
    channel_message_id: str | None
    status: CampaignMessageStatus
    error: str | None
    sent_at: datetime | None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    created_at: datetime


class CampaignStatsOut(BaseModel):
    campaign_id: uuid.UUID
    status: CampaignStatus
    audience_size: int
    queued: int
    sent: int
    delivered: int
    read: int
    failed: int
    # Campaigns v1 Step 05 — Email tracking. Always present in the
    # response (0 for WA campaigns) so the frontend can decide whether
    # to render the Email funnel without a separate lookup.
    opened: int = 0
    clicked: int = 0
    bounced: int = 0
    unsubscribed: int = 0


class CampaignStartResponse(BaseModel):
    campaign_id: uuid.UUID
    status: CampaignStatus
    audience_size: int
    chunks_enqueued: int
    scheduled_at: datetime | None


class CampaignDashboardStatsOut(BaseModel):
    """Org-wide campaign KPIs for the current calendar month, powering
    the KPI cards at the top of the Campaigns page. ``delivery_rate``
    and ``read_rate`` are `None` when their denominator is zero so the
    frontend renders "—" instead of a misleading 0%."""

    since: datetime
    sent: int
    delivered: int
    read: int
    delivery_rate: float | None
    read_rate: float | None


class CampaignReadinessItem(BaseModel):
    """One blocker or warning surfaced by the readiness pre-flight."""

    code: str
    message: str


class CampaignReadinessOut(BaseModel):
    """Campaigns v1 Step 07c — structured pre-flight for the Start
    button. The wizard + list-page consume this to render red / amber
    banners with fix-links before firing the actual ``/start`` call."""

    campaign_id: uuid.UUID
    channel: str
    audience_size: int
    eligible_count: int
    excluded_opted_out: int = 0
    excluded_no_email: int = 0
    excluded_bounced: int = 0
    blockers: list[CampaignReadinessItem] = []
    warnings: list[CampaignReadinessItem] = []
