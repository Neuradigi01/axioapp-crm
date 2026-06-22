"""Pydantic v2 schemas for the WhatsApp account connect surface.

`WhatsAppConnectIn` is the HTTP body for `POST /connect`. The operator
pastes the five Meta-provided values + chooses a verify_token (any
random string they'll also configure in the Meta webhook console).

`WhatsAppStatusOut` is the projection both `GET /status` and the
connect/test endpoints return. It DELIBERATELY OMITS `access_token` and
`app_secret` — the encrypted forms live in the DB, plaintext never
leaves the server.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.shared.schemas import ORMModel


WhatsAppIntegrationStatus = Literal[
    "connected", "disconnected", "expired", "error"
]


class WhatsAppConnectIn(BaseModel):
    """HTTP body for `POST /api/v1/integrations/whatsapp/connect`.

    `phone_id` and `waba_id` are pure numeric strings in Meta's docs —
    we keep them as Text to dodge ID-length surprises. `api_version`
    defaults to `v18.0` to match the existing adapter's default."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    phone_id: str = Field(min_length=1, max_length=64)
    waba_id: str = Field(min_length=1, max_length=64)
    access_token: str = Field(min_length=1)
    app_secret: str = Field(min_length=1, max_length=255)
    verify_token: str = Field(min_length=1, max_length=255)
    api_version: str = Field(default="v18.0", max_length=16)
    # Step 3.5.15 — per-org rate cap (msg/sec). Free-tier ~50, verified
    # accounts up to 1000. Operator-editable; default 50.
    rate_limit_per_sec: int = Field(default=50, ge=1, le=1000)


class EmbeddedSignupConfigOut(BaseModel):
    """Response shape for `GET /embedded-signup/config`.

    Every field is public-safe — the Meta App ID and Configuration ID
    are designed to live in the browser-side `FB.init` / `FB.login`
    calls. Returning them via an authenticated endpoint (rather than
    baking into a static bundle) keeps deploy-time config swaps cheap
    and avoids shipping per-environment build artefacts."""

    app_id: str
    config_id: str
    graph_api_version: str


class EmbeddedSignupExchangeIn(BaseModel):
    """HTTP body for `POST /embedded-signup/exchange`.

    The frontend popup (Step 3) hands us the three values it harvested
    from Meta's FB.login response: the short-lived auth `code`, the
    selected `phone_number_id`, and its parent `waba_id`. The backend
    does the heavy lifting from there — exchange, fetch, subscribe,
    register, persist."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=512)
    phone_number_id: str = Field(min_length=1, max_length=64)
    waba_id: str = Field(min_length=1, max_length=64)


class EmbeddedSignupExchangeOut(BaseModel):
    """Response shape for `POST /embedded-signup/exchange`.

    The Settings UI uses this to render the success state immediately
    after the popup closes — no follow-up `GET /status` call needed.
    `phone_numbers_available` + `selected_index` surface Phase-9-pending
    multi-number context so the frontend can warn the customer when
    their WABA has more phones than we connected."""

    status: WhatsAppIntegrationStatus
    phone_id: str
    waba_id: str
    display_phone_number: str
    verified_name: Optional[str] = None
    api_version: str
    rate_limit_per_sec: int
    phone_numbers_available: int
    selected_index: int
    messaging_limit_tier: Optional[str] = None
    quality_rating: Optional[str] = None


class WhatsAppStatusOut(ORMModel):
    """Projection returned by `connect`, `test`, and `GET /status`.

    NEVER includes `access_token` or `app_secret` — those are encrypted
    at rest and decrypted only inside the dispatch / webhook paths."""

    status: WhatsAppIntegrationStatus
    phone_id: Optional[str] = None
    waba_id: Optional[str] = None
    display_phone_number: Optional[str] = None
    verified_name: Optional[str] = None
    api_version: Optional[str] = None
    rate_limit_per_sec: Optional[int] = None
    last_error: Optional[str] = None
    connected_at: Optional[datetime] = None


WhatsAppTemplateStatus = Literal[
    "APPROVED", "PENDING", "REJECTED", "DISABLED"
]
WhatsAppTemplateCategory = Literal[
    "MARKETING", "UTILITY", "AUTHENTICATION"
]
WhatsAppTemplateHeaderType = Literal[
    "TEXT", "IMAGE", "VIDEO", "DOCUMENT"
]


class WhatsAppTemplateRead(ORMModel):
    """Row projection for `GET /api/v1/integrations/whatsapp/templates`.

    Used by the Settings UI template list (Step 3.5.4), the campaign
    create-modal picker (Step 3.5.5), and the management surface
    introduced in Step 8 (CRUD + submit). `variable_count` lets the
    picker render the right number of variable-binding inputs without
    parsing the body."""

    id: uuid.UUID
    name: str
    language: str
    category: str
    status: str
    body: str
    header_type: Optional[str] = None
    header_text: Optional[str] = None
    footer_text: Optional[str] = None
    variable_count: int
    meta_template_id: Optional[str] = None
    # whatsapp-platform-upgrade Step 8 — operator-side lifecycle +
    # rejection metadata + structured component payload.
    submission_status: str = "draft"
    rejection_reason: Optional[str] = None
    submitted_by_user_id: Optional[uuid.UUID] = None
    submitted_at: Optional[datetime] = None
    body_components: Optional[list[dict[str, Any]]] = None
    last_synced_at: datetime


# --- Template management (whatsapp-platform-upgrade Step 8) ----------
#
# Meta-published limits the schema enforces at the boundary. These
# match developers.facebook.com/docs/whatsapp/business-management-api
# /message-templates limits as of API v19.0; tighten when Meta tightens.


_TEMPLATE_BODY_MAX = 1024
_TEMPLATE_HEADER_TEXT_MAX = 60
_TEMPLATE_FOOTER_MAX = 60
_TEMPLATE_BUTTON_TITLE_MAX = 25
_TEMPLATE_BUTTON_URL_MAX = 2000
_TEMPLATE_BUTTON_PHONE_MAX = 20
_TEMPLATE_BUTTONS_MAX = 10  # Meta allows up to 10 mixed buttons
_TEMPLATE_NAME_RE = re.compile(r"^[a-z0-9_]+$")

WhatsAppTemplateButtonType = Literal["QUICK_REPLY", "URL", "PHONE_NUMBER"]


class WhatsAppTemplateButton(BaseModel):
    """One button entry inside ``body_components`` BUTTONS row.

    Meta supports three kinds — quick-reply (the recipient taps to
    send the title text back as a webhook reply), URL (opens a link),
    and phone-number (opens dialer). A single template can mix URL
    and PHONE_NUMBER call-to-action buttons OR have a quick-reply
    pack — never both per Meta's spec; the parent ``body_components``
    validator enforces the rule."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: WhatsAppTemplateButtonType
    text: str = Field(min_length=1, max_length=_TEMPLATE_BUTTON_TITLE_MAX)
    url: Optional[str] = Field(
        default=None,
        max_length=_TEMPLATE_BUTTON_URL_MAX,
        pattern=r"^https?://.+",
    )
    phone_number: Optional[str] = Field(
        default=None, max_length=_TEMPLATE_BUTTON_PHONE_MAX
    )

    @model_validator(mode="after")
    def _check_button_payload(self) -> "WhatsAppTemplateButton":
        if self.type == "URL" and not self.url:
            raise ValueError("URL buttons require a `url`.")
        if self.type == "PHONE_NUMBER" and not self.phone_number:
            raise ValueError(
                "PHONE_NUMBER buttons require a `phone_number`."
            )
        if self.type == "QUICK_REPLY" and (self.url or self.phone_number):
            raise ValueError(
                "QUICK_REPLY buttons must not carry url / phone_number."
            )
        return self


class WhatsAppTemplateUpsert(BaseModel):
    """Body of ``POST /api/v1/whatsapp/templates`` (create draft) and
    ``PATCH /{id}`` (edit while draft/rejected).

    Meta enforces the validation rules below at submit-time; we
    apply them at create + edit time so the UI catches mistakes
    before they reach Meta. ``variable_count`` is derived from the
    ``{{n}}`` placeholders in ``body`` — the service computes it,
    not the client."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=512, pattern=r"^[a-z0-9_]+$")
    language: str = Field(min_length=2, max_length=16)
    category: Literal["MARKETING", "UTILITY", "AUTHENTICATION"]
    body: str = Field(min_length=1, max_length=_TEMPLATE_BODY_MAX)
    header_type: Optional[Literal["TEXT", "IMAGE", "VIDEO", "DOCUMENT"]] = None
    header_text: Optional[str] = Field(
        default=None, max_length=_TEMPLATE_HEADER_TEXT_MAX
    )
    footer_text: Optional[str] = Field(
        default=None, max_length=_TEMPLATE_FOOTER_MAX
    )
    buttons: list[WhatsAppTemplateButton] = Field(
        default_factory=list, max_length=_TEMPLATE_BUTTONS_MAX
    )

    @model_validator(mode="after")
    def _check_buttons_and_header(self) -> "WhatsAppTemplateUpsert":
        # TEXT header carries `header_text`; media headers (IMAGE /
        # VIDEO / DOCUMENT) come with a sample asset attached at
        # submit-time and don't carry text. Reject the mismatch early.
        if self.header_type == "TEXT" and not self.header_text:
            raise ValueError(
                "TEXT header requires `header_text`."
            )
        if self.header_type not in (None, "TEXT") and self.header_text:
            raise ValueError(
                "Media headers (IMAGE/VIDEO/DOCUMENT) don't take "
                "`header_text` — supply a sample asset at submit time."
            )

        # Buttons: mixing quick-reply with CTA isn't allowed (Meta spec).
        kinds = {b.type for b in self.buttons}
        if "QUICK_REPLY" in kinds and len(kinds) > 1:
            raise ValueError(
                "Quick-reply buttons cannot be mixed with URL or "
                "phone-number buttons in the same template."
            )
        return self


class WhatsAppTemplateSubmissionOut(BaseModel):
    """Response shape for ``POST /templates/{id}/submit``.

    Returns the row's new status + the Meta-side template id so the UI
    can swap state without a follow-up fetch. ``meta_status`` is the
    raw Meta value (``PENDING`` immediately after submit; ``APPROVED`` /
    ``REJECTED`` once the webhook lands)."""

    id: uuid.UUID
    submission_status: str
    meta_template_id: Optional[str] = None
    meta_status: Optional[str] = None


class WhatsAppTemplateSyncOut(BaseModel):
    """Counts returned by `POST /api/v1/integrations/whatsapp/templates/sync`.

    The Settings UI uses these in a toast: "3 added, 1 updated, 0 removed".
    `total` is the post-sync row count for the org (added + unchanged)."""

    added: int
    updated: int
    removed: int
    total: int


class WhatsAppCapacityOut(BaseModel):
    """Response shape for `GET /api/v1/integrations/whatsapp/capacity`
    — drives the campaign create modal's quota banner (Step 3.5.16).

    `daily_limit` and `remaining` are both `-1` when `is_unlimited`
    is true; the UI uses those sentinels to hide the progress bar
    and the "X remaining" copy. `usage_percent` is capped at 100."""

    tier: str
    tier_label: str
    daily_limit: int
    used_today: int
    remaining: int
    usage_percent: int
    is_unlimited: bool


__all__ = [
    "EmbeddedSignupConfigOut",
    "EmbeddedSignupExchangeIn",
    "EmbeddedSignupExchangeOut",
    "WhatsAppCapacityOut",
    "WhatsAppConnectIn",
    "WhatsAppIntegrationStatus",
    "WhatsAppStatusOut",
    "WhatsAppTemplateButton",
    "WhatsAppTemplateButtonType",
    "WhatsAppTemplateCategory",
    "WhatsAppTemplateHeaderType",
    "WhatsAppTemplateRead",
    "WhatsAppTemplateStatus",
    "WhatsAppTemplateSubmissionOut",
    "WhatsAppTemplateSyncOut",
    "WhatsAppTemplateUpsert",
]
