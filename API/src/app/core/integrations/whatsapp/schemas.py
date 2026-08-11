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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.shared.schemas import ORMModel

WhatsAppIntegrationStatus = Literal["connected", "disconnected", "expired", "error"]


class WhatsAppConnectIn(BaseModel):
    """HTTP body for `POST /api/v1/integrations/whatsapp/connect`.

    `phone_id` and `waba_id` are pure numeric strings in Meta's docs —
    we keep them as Text to dodge ID-length surprises. `api_version`
    defaults to `v18.0` to match the existing adapter's default."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    phone_id: str = Field(min_length=1, max_length=64)
    waba_id: str = Field(min_length=1, max_length=64)
    access_token: str = Field(min_length=1)
    # Optional — omit to reuse the platform-level `WHATSAPP_APP_SECRET`
    # env var. Only paste a per-org value when this org's WABA lives
    # under a different Meta App than the platform default.
    app_secret: str | None = Field(default=None, max_length=255)
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
    verified_name: str | None = None
    api_version: str
    rate_limit_per_sec: int
    phone_numbers_available: int
    selected_index: int
    messaging_limit_tier: str | None = None
    quality_rating: str | None = None


class WhatsAppStatusOut(ORMModel):
    """Projection returned by `connect`, `test`, and `GET /status`.

    NEVER includes `access_token` or `app_secret` — those are encrypted
    at rest and decrypted only inside the dispatch / webhook paths."""

    status: WhatsAppIntegrationStatus
    phone_id: str | None = None
    waba_id: str | None = None
    display_phone_number: str | None = None
    verified_name: str | None = None
    api_version: str | None = None
    rate_limit_per_sec: int | None = None
    last_error: str | None = None
    connected_at: datetime | None = None


WhatsAppTemplateStatus = Literal["APPROVED", "PENDING", "REJECTED", "DISABLED"]
WhatsAppTemplateCategory = Literal["MARKETING", "UTILITY", "AUTHENTICATION"]
WhatsAppTemplateHeaderType = Literal["TEXT", "IMAGE", "VIDEO", "DOCUMENT"]


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
    header_type: str | None = None
    header_text: str | None = None
    footer_text: str | None = None
    variable_count: int
    meta_template_id: str | None = None
    # whatsapp-platform-upgrade Step 8 — operator-side lifecycle +
    # rejection metadata + structured component payload.
    submission_status: str = "draft"
    rejection_reason: str | None = None
    submitted_by_user_id: uuid.UUID | None = None
    submitted_at: datetime | None = None
    body_components: list[dict[str, Any]] | None = None
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
    url: str | None = Field(
        default=None,
        max_length=_TEMPLATE_BUTTON_URL_MAX,
        pattern=r"^https?://.+",
    )
    phone_number: str | None = Field(default=None, max_length=_TEMPLATE_BUTTON_PHONE_MAX)

    @model_validator(mode="after")
    def _check_button_payload(self) -> WhatsAppTemplateButton:
        if self.type == "URL" and not self.url:
            raise ValueError("URL buttons require a `url`.")
        if self.type == "PHONE_NUMBER" and not self.phone_number:
            raise ValueError("PHONE_NUMBER buttons require a `phone_number`.")
        if self.type == "QUICK_REPLY" and (self.url or self.phone_number):
            raise ValueError("QUICK_REPLY buttons must not carry url / phone_number.")
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
    header_type: Literal["TEXT", "IMAGE", "VIDEO", "DOCUMENT"] | None = None
    header_text: str | None = Field(default=None, max_length=_TEMPLATE_HEADER_TEXT_MAX)
    footer_text: str | None = Field(default=None, max_length=_TEMPLATE_FOOTER_MAX)
    buttons: list[WhatsAppTemplateButton] = Field(
        default_factory=list, max_length=_TEMPLATE_BUTTONS_MAX
    )

    @model_validator(mode="after")
    def _check_buttons_and_header(self) -> WhatsAppTemplateUpsert:
        # TEXT header carries `header_text`; media headers (IMAGE /
        # VIDEO / DOCUMENT) come with a sample asset attached at
        # submit-time and don't carry text. Reject the mismatch early.
        if self.header_type == "TEXT" and not self.header_text:
            raise ValueError("TEXT header requires `header_text`.")
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
    meta_template_id: str | None = None
    meta_status: str | None = None


# --- Per-template performance (whatsapp-platform-upgrade Step 10) ----


class WhatsAppTemplateDailyBucket(BaseModel):
    """One day-grain bucket on the performance line chart."""

    date: str
    sent: int
    delivered: int
    read: int
    failed: int


class WhatsAppTemplateFailureGroup(BaseModel):
    """One grouped failure reason on the breakdown table.

    `bucket` is a stable machine key (``rate_limited`` / ``opted_out``
    / ``invalid_number`` / ``template_paused`` / ``other``); `label`
    is the operator-facing string."""

    bucket: str
    label: str
    count: int


# --- Phone health (whatsapp-platform-upgrade Step 12) ---------------


WhatsAppQualityRating = Literal["GREEN", "YELLOW", "RED", "UNKNOWN"]


class WhatsAppPhoneHealthEventRead(BaseModel):
    """One timeline-chart point. `occurred_at` is the wall-clock from
    Meta (or now() for events we wrote without a Meta timestamp).
    `old_value` / `new_value` are the diff shape — the UI surfaces
    the verbatim values in the tooltip."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phone_id: str
    event_type: str
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    occurred_at: datetime
    recorded_at: datetime


class WhatsAppPhoneHealthRead(BaseModel):
    """Aggregate read for the phone-health card + dashboard widget.

    Carries the live snapshot (quality / tier / restrictions /
    throughput) plus the 30-day event timeline and a quick-glance
    derived `recovery_keys[]` list the UI uses to render the recovery
    checklist when quality is degraded."""

    phone_id: str
    display_phone_number: str
    verified_name: str | None = None
    quality_rating: WhatsAppQualityRating = "UNKNOWN"
    messaging_limit_tier: str | None = None
    tier_label: str | None = None
    name_status: str | None = None
    throughput: int | None = None
    restrictions: list[dict[str, Any]] = Field(default_factory=list)
    health_synced_at: datetime | None = None
    daily_limit: int = 0
    used_today: int = 0
    remaining: int = 0
    usage_percent: int = 0
    is_unlimited: bool = False
    recovery_keys: list[str] = Field(default_factory=list)
    events: list[WhatsAppPhoneHealthEventRead] = Field(default_factory=list)


# --- AI settings (whatsapp-platform-upgrade Step 19) -----------------


class AISettingsRead(BaseModel):
    """Response shape for ``GET /api/v1/integrations/whatsapp/ai/settings``.

    The per-conversation ``ai_handling`` toggle lives on
    `tbl_conversations` (existing column); these are org-wide knobs."""

    model_config = ConfigDict(from_attributes=True)

    ai_handling_default_enabled: bool = False
    ai_confidence_threshold: float = 0.6
    ai_handover_keywords: list[str] = Field(default_factory=list)
    ai_system_prompt: str | None = None


class AISettingsPatch(BaseModel):
    """Body of ``PATCH /api/v1/integrations/whatsapp/ai/settings``.
    Every field optional; only supplied fields are applied."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ai_handling_default_enabled: bool | None = None
    ai_confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    ai_handover_keywords: list[str] | None = Field(default=None, max_length=50)
    ai_system_prompt: str | None = Field(default=None, max_length=4096)


class AIHandlingToggle(BaseModel):
    """Body of ``PATCH /api/v1/conversations/{id}/ai-handling``."""

    model_config = ConfigDict(extra="forbid")

    ai_handling: bool


# --- Assignment rules (whatsapp-platform-upgrade Step 18) ------------


AssignmentStrategyLiteral = Literal["round_robin", "load_balanced", "tag_based", "team_based"]


class AssignmentRuleUpsert(BaseModel):
    """Body of ``POST /api/v1/integrations/whatsapp/assignment-rules``
    and ``PATCH /{id}``. Per-strategy `config` shape:

      * ``round_robin``   — ``{"eligible_user_ids": [uuid, ...]}``
      * ``load_balanced`` — ``{"eligible_user_ids": [uuid, ...],
                               "cap_per_user": int|null}``
      * ``tag_based``     — ``{"mapping": {tag_id: user_id, ...}}``
      * ``team_based``    — ``{"team_id": uuid}``

    Cross-field validation: every strategy except ``team_based``
    needs a non-empty ``eligible_user_ids`` / ``mapping``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=128)
    strategy: AssignmentStrategyLiteral
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    skip_outside_hours: bool = False

    @model_validator(mode="after")
    def _check_config(self) -> AssignmentRuleUpsert:
        cfg = self.config or {}
        if self.strategy in ("round_robin", "load_balanced"):
            users = cfg.get("eligible_user_ids")
            if not isinstance(users, list) or not users:
                raise ValueError("`eligible_user_ids` must be a non-empty list.")
            if len(users) > 200:
                raise ValueError("`eligible_user_ids` cannot exceed 200 entries.")
            for u in users:
                # Cheapest validation we can do client-side; UUID
                # parsing failure surfaces a clear 422.
                try:
                    uuid.UUID(str(u))
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"`eligible_user_ids` contains a non-UUID value: {u!r}"
                    ) from exc
            if self.strategy == "load_balanced":
                cap = cfg.get("cap_per_user")
                if cap is not None and (not isinstance(cap, int) or cap <= 0):
                    raise ValueError("`cap_per_user` must be a positive integer or null.")
        elif self.strategy == "tag_based":
            mapping = cfg.get("mapping")
            if not isinstance(mapping, dict) or not mapping:
                raise ValueError("`mapping` must be a non-empty {tag_id: user_id} object.")
            for tag_id, user_id in mapping.items():
                try:
                    uuid.UUID(str(tag_id))
                    uuid.UUID(str(user_id))
                except (TypeError, ValueError) as exc:
                    raise ValueError("`mapping` keys + values must be UUIDs.") from exc
        elif self.strategy == "team_based":
            team_id = cfg.get("team_id")
            if not team_id:
                raise ValueError("`team_id` is required for team_based.")
            try:
                uuid.UUID(str(team_id))
            except (TypeError, ValueError) as exc:
                raise ValueError("`team_id` must be a UUID.") from exc
        return self


class AssignmentRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    strategy: str
    config: dict[str, Any]
    enabled: bool
    priority: int
    skip_outside_hours: bool
    last_assigned_user_id: uuid.UUID | None = None
    created_by_user_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class AssignmentRuleReorder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


# --- Keyword rules (whatsapp-platform-upgrade Step 17) ---------------


KeywordMatchTypeLiteral = Literal["contains", "exact", "regex"]
KeywordActionTypeLiteral = Literal[
    "reply_text",
    "reply_template",
    "tag_conversation",
    "assign_to_user",
    "escalate_to_ai",
]


class KeywordActionPayload(BaseModel):
    """One action attached to a rule. `action_config` shape varies by
    `action_type`:

      * ``reply_text``         → ``{"text": "..."}``
      * ``reply_template``     → ``{"template_id": "<uuid>"}``
      * ``tag_conversation``   → ``{"tag_id": "<uuid>"}``
      * ``assign_to_user``     → ``{"user_id": "<uuid>"}``
      * ``escalate_to_ai``     → ``{}`` (toggles `ai_handling=true`)

    The engine validates the config shape per type at dispatch time
    — keep this schema permissive so a future action type can be
    added without a migration to the JSONB."""

    model_config = ConfigDict(extra="forbid")

    action_type: KeywordActionTypeLiteral
    action_config: dict[str, Any] = Field(default_factory=dict)
    position: int = Field(default=0, ge=0, le=100)


class KeywordRuleUpsert(BaseModel):
    """Body of ``POST /api/v1/integrations/whatsapp/keyword-rules`` +
    ``PATCH /{id}``. On PATCH, every field is optional — partial
    updates only touch what's supplied."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=128)
    keywords: list[str] = Field(min_length=1, max_length=50)
    match_type: KeywordMatchTypeLiteral = "contains"
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    actions: list[KeywordActionPayload] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _check_keyword_lengths(self) -> KeywordRuleUpsert:
        # Regex patterns get extra scrutiny — cap length at 200 chars
        # to bound match runtime; the engine's eval also wraps in a
        # try/except so a bad regex doesn't crash the inbound webhook.
        cap = 200 if self.match_type == "regex" else 256
        for k in self.keywords:
            if not k.strip():
                raise ValueError("Keywords cannot be blank.")
            if len(k) > cap:
                raise ValueError(f"Keyword exceeds the {cap}-character limit.")
        return self


class KeywordActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action_type: str
    action_config: dict[str, Any]
    position: int


class KeywordRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    keywords: list[str]
    match_type: str
    enabled: bool
    priority: int
    created_by_user_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    actions: list[KeywordActionRead] = Field(default_factory=list)


class KeywordRuleReorder(BaseModel):
    """Body of ``POST /keyword-rules/reorder`` — a list of rule ids
    in the order they should evaluate. Server reassigns `priority`
    based on list position so the operator can drag-to-reorder
    without picking explicit numbers."""

    model_config = ConfigDict(extra="forbid")

    rule_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class RuleTestRequest(BaseModel):
    """Body of ``POST /keyword-rules/test``. Dry-run — evaluates every
    enabled rule against `text` + returns the first match's id +
    its actions. Does NOT actually send / tag / assign anything."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=4096)


class RuleTestResponse(BaseModel):
    matched_rule_id: uuid.UUID | None = None
    matched_rule_name: str | None = None
    actions: list[KeywordActionRead] = Field(default_factory=list)


# --- Auto-reply (whatsapp-platform-upgrade Step 16) ------------------


class AutoReplySettingsRead(BaseModel):
    """Response shape for ``GET /api/v1/integrations/whatsapp/auto-reply/settings``.

    Carries every field the operator's toggle row + textarea + linked-
    template pickers need. Reuses the Step-11 `greeting_message` /
    `away_message` / `business_hours` from the same row — the
    auto-reply section on the business-profile page edits the same
    underlying record."""

    model_config = ConfigDict(from_attributes=True)

    greeting_enabled: bool = False
    greeting_message: str | None = None
    greeting_template_id: uuid.UUID | None = None

    away_enabled: bool = False
    away_message: str | None = None
    away_template_id: uuid.UUID | None = None

    business_hours: list[dict[str, Any]] = Field(default_factory=list)


class AutoReplySettingsPatch(BaseModel):
    """Body of ``PATCH /api/v1/integrations/whatsapp/auto-reply/settings``.

    Every field optional — only supplied fields are applied. The
    service enforces "if you enable greeting, you must have message
    OR template_id" — both NULL with the toggle on is rejected
    at the boundary so the auto-reply pipeline never fires an empty
    string."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    greeting_enabled: bool | None = None
    greeting_message: str | None = Field(default=None, max_length=4096)
    greeting_template_id: uuid.UUID | None = None

    away_enabled: bool | None = None
    away_message: str | None = Field(default=None, max_length=4096)
    away_template_id: uuid.UUID | None = None


# --- Business profile editor (whatsapp-platform-upgrade Step 11) ----


# Meta-published verticals
# https://developers.facebook.com/docs/whatsapp/cloud-api/reference
# /business-profiles#vertical
WhatsAppBusinessVertical = Literal[
    "UNDEFINED",
    "OTHER",
    "AUTO",
    "BEAUTY",
    "APPAREL",
    "EDU",
    "ENTERTAIN",
    "EVENT_PLAN",
    "FINANCE",
    "GROCERY",
    "GOVT",
    "HOTEL",
    "HEALTH",
    "NONPROFIT",
    "PROF_SERVICES",
    "RETAIL",
    "TRAVEL",
    "RESTAURANT",
]


class WhatsAppBusinessHoursInterval(BaseModel):
    """One open-close interval within a single day. Times are local
    to the operator (timezone display is the page's concern, not the
    schema's). Stored as ``HH:MM`` strings rather than time objects
    so the JSONB shape is human-readable and JSON-clean."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    open: str = Field(pattern=r"^\d{2}:\d{2}$")
    close: str = Field(pattern=r"^\d{2}:\d{2}$")


class WhatsAppBusinessHoursDay(BaseModel):
    """One day's schedule. `day` is 0..6 (Monday..Sunday, ISO style).
    Closed days emit an empty `intervals` list. Multiple intervals per
    day support split-shift schedules (e.g. 10:00-13:00 + 17:00-21:00)."""

    model_config = ConfigDict(extra="forbid")

    day: int = Field(ge=0, le=6)
    intervals: list[WhatsAppBusinessHoursInterval] = Field(default_factory=list)


class WhatsAppBusinessProfilePatch(BaseModel):
    """Body of ``PATCH /api/v1/integrations/whatsapp/business-profile``.

    Every field optional — only supplied fields are pushed to Meta.
    Field length / format caps match Meta's documented limits +
    `tbl_whatsapp_account_configs` column widths. Websites are capped
    at 2 entries per Meta's spec."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    about: str | None = Field(default=None, max_length=139)
    description: str | None = Field(default=None, max_length=512)
    address: str | None = Field(default=None, max_length=256)
    email: str | None = Field(default=None, max_length=128)
    websites: list[str] | None = Field(default=None, max_length=2)
    vertical: WhatsAppBusinessVertical | None = None
    # Core-CRM-only fields. Stored verbatim; Step 16 reads them.
    business_hours: list[WhatsAppBusinessHoursDay] | None = None
    greeting_message: str | None = Field(default=None, max_length=4096)
    away_message: str | None = Field(default=None, max_length=4096)


class WhatsAppBusinessProfileRead(BaseModel):
    """Response shape for ``GET /api/v1/integrations/whatsapp/business-profile``.

    Carries every field the editor needs to render (Meta-side profile
    + CRM-side hours + greeting/away) plus `last_synced_at` so the UI
    can warn when the row is stale."""

    model_config = ConfigDict(from_attributes=True)

    phone_id: str
    display_phone_number: str
    verified_name: str | None = None
    about: str | None = None
    description: str | None = None
    address: str | None = None
    email: str | None = None
    websites: list[str] = Field(default_factory=list)
    vertical: str | None = None
    profile_picture_url: str | None = None
    last_synced_at: datetime | None = None
    business_hours: list[WhatsAppBusinessHoursDay] = Field(default_factory=list)
    greeting_message: str | None = None
    away_message: str | None = None


class WhatsAppTemplatePerformanceOut(BaseModel):
    """Response shape for ``GET /templates/{id}/performance?range=...``.

    Empty-state friendly — counts default to zero; `daily` and
    `failures` may be empty lists when the template has never been
    sent inside the range."""

    template_id: uuid.UUID
    range_key: Literal["7d", "30d", "90d"]
    range_start: datetime
    range_end: datetime

    sent: int
    delivered: int
    read: int
    replied: int
    click_through: int
    failed: int

    delivery_rate: float
    read_rate: float
    reply_rate: float

    daily: list[WhatsAppTemplateDailyBucket] = Field(default_factory=list)
    failures: list[WhatsAppTemplateFailureGroup] = Field(default_factory=list)
    used_in_campaigns: int = 0


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
    "AIHandlingToggle",
    "AISettingsPatch",
    "AISettingsRead",
    "AssignmentRuleRead",
    "AssignmentRuleReorder",
    "AssignmentRuleUpsert",
    "AssignmentStrategyLiteral",
    "AutoReplySettingsPatch",
    "AutoReplySettingsRead",
    "KeywordActionPayload",
    "KeywordActionRead",
    "KeywordActionTypeLiteral",
    "KeywordMatchTypeLiteral",
    "KeywordRuleRead",
    "KeywordRuleReorder",
    "KeywordRuleUpsert",
    "RuleTestRequest",
    "RuleTestResponse",
    "WhatsAppBusinessHoursDay",
    "WhatsAppBusinessHoursInterval",
    "WhatsAppBusinessProfilePatch",
    "WhatsAppBusinessProfileRead",
    "WhatsAppBusinessVertical",
    "WhatsAppPhoneHealthEventRead",
    "WhatsAppPhoneHealthRead",
    "WhatsAppQualityRating",
    "WhatsAppTemplateButton",
    "WhatsAppTemplateButtonType",
    "WhatsAppTemplateCategory",
    "WhatsAppTemplateDailyBucket",
    "WhatsAppTemplateFailureGroup",
    "WhatsAppTemplateHeaderType",
    "WhatsAppTemplatePerformanceOut",
    "WhatsAppTemplateRead",
    "WhatsAppTemplateStatus",
    "WhatsAppTemplateSubmissionOut",
    "WhatsAppTemplateSyncOut",
    "WhatsAppTemplateUpsert",
]
