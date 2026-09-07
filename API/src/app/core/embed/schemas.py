"""Pydantic v2 schemas for the embeddable-widget keys API.

`EmbedKeyIssue` is the request body for `POST /embed/keys`.
`EmbedKeyRead` is the row projection — used by `GET /embed/keys` and
the side-by-side row in `EmbedKeyIssueResponse`. **`EmbedKeyRead` does
NOT expose the plaintext secret.**
`EmbedKeyIssueResponse` is the response for `POST /embed/keys` only —
it carries the plaintext `secret` exactly once. The secret is never
returned by any other endpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from src.app.shared.schemas import ORMModel


class EmbedKeyIssue(BaseModel):
    """Body for `POST /embed/keys`. `name` is an optional friendly
    label for the Owner to remember what the key is for.

    ``form_id`` pins the new key to a specific lead-form. Optional —
    when omitted the service falls back to the org's default form so
    scripts / older callers that don't specify a form keep working.
    Rejected with 422 when the form belongs to a different org or is
    soft-deleted.
    """

    name: str | None = Field(default=None, max_length=128)
    form_id: uuid.UUID | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class EmbedKeyRead(ORMModel):
    """Row projection. Never includes the plaintext secret — only
    the 11-char prefix so the Owner can identify which key is which."""

    id: uuid.UUID
    org_id: uuid.UUID
    name: str | None
    prefix: str
    created_by: uuid.UUID
    last_used_at: datetime | None
    last_used_ip: str | None
    revoked_at: datetime | None
    revoked_by: uuid.UUID | None
    grace_expires_at: datetime | None = None
    resource_type: str = "lead_form"
    resource_id: uuid.UUID | None = None
    allowed_origins: list[str] = Field(default_factory=list)
    rate_limit_per_hour: int = 300
    created_at: datetime


class EmbedKeyIssueResponse(ORMModel):
    """Response for `POST /embed/keys` only. The `secret` field
    appears here once and is never retrievable again — the Owner
    must copy it before navigating away."""

    id: uuid.UUID
    name: str | None
    prefix: str
    secret: str
    created_at: datetime


class AiAssistantEmbedKeyIssue(BaseModel):
    """Body for ``POST /embed/ai-assistants/{id}/keys`` (Step 14).

    ``allowed_origins`` is an origin allow-list (advisory — real
    defence is the fail-closed rate limiter + budget cap + Turnstile).
    ``rate_limit_per_hour`` overrides the 300-req/hour default per
    key; capped at 5000 so a runaway config can't nullify the org
    aggregate cap.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=128)
    allowed_origins: list[str] = Field(default_factory=list, max_length=32)
    rate_limit_per_hour: int | None = Field(default=None, ge=1, le=5000)

    @field_validator("allowed_origins")
    @classmethod
    def _origins_shape(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for raw in v:
            trimmed = raw.strip().lower()
            if len(trimmed) < 1 or len(trimmed) > 253:
                raise ValueError("origin length must be 1..253 chars")
            if not (trimmed.startswith("http://") or trimmed.startswith("https://")):
                raise ValueError("origin must start with http:// or https://")
            out.append(trimmed)
        return out


class SubmissionAttribution(BaseModel):
    """UTM + referrer payload captured by the widget at render time.

    Every field is optional — visitors arriving via direct traffic
    have no UTM parameters or referrer. Step 9's submission log
    surfaces whichever fields landed.

    Schema is frozen for v1 — additional fields land in a separate
    sibling JSON blob rather than expanding this shape, so the
    reporting surface stays stable across channels.
    """

    referrer: str | None = Field(default=None, max_length=2048)
    landing_url: str | None = Field(default=None, max_length=2048)
    utm_source: str | None = Field(default=None, max_length=255)
    utm_medium: str | None = Field(default=None, max_length=255)
    utm_campaign: str | None = Field(default=None, max_length=255)
    utm_content: str | None = Field(default=None, max_length=255)
    utm_term: str | None = Field(default=None, max_length=255)


class EmbedSubmission(BaseModel):
    """Request body for `POST /embed/leads`.

    The widget JS bundle builds this payload from the form values +
    auto-captured attribution data. Authentication is via either the
    `X-FurniCRM-Key` request header OR the `embed_key` body field
    (header takes precedence when both are present).
    """

    embed_key: str | None = Field(default=None, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    interest: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=2000)
    # Honeypot — bots fill in EVERY visible field including hidden ones.
    # Empty / missing for legit humans. Non-empty triggers a silent 200
    # (no lead created) so bots don't learn they were caught.
    honeypot: str | None = Field(default=None, max_length=255)
    # When the widget rendered the form. Step 8 enforces a min-fill-time
    # check against this — submissions arriving < `min_fill_time_ms` after
    # render are silently dropped.
    rendered_at: datetime | None = None
    # Google reCAPTCHA v3 token, populated by the widget when the org
    # has enabled reCAPTCHA in their widget config. Verified server-side
    # against the org's secret key; low-score or invalid tokens silent-drop.
    recaptcha_token: str | None = Field(default=None, max_length=4096)
    # Org-defined contact custom fields the Owner has opted IN to the
    # widget (Step 10). Each key matches a row in `custom_field_definitions`
    # for `entity_type='contact'`. Values land in the contact's
    # `custom_data` JSONB at create time.
    custom_data: dict[str, Any] = Field(default_factory=dict)
    attribution: SubmissionAttribution = Field(default_factory=SubmissionAttribution)
    # whatsapp-platform-upgrade Step 22 — DPDP consent checkbox.
    # The widget renders a required-by-default checkbox; the submit
    # button stays disabled until it's ticked. When true the embed
    # submission service flips the contact to `opted_in` with
    # `source='form_widget'` and writes a consent-event row carrying
    # the submitted payload as evidence. False / missing leaves the
    # contact at the org's default ("never_contacted").
    whatsapp_consent: bool = Field(default=False)

    model_config = ConfigDict(str_strip_whitespace=True)


class EmbedSubmissionResponse(BaseModel):
    """Response for `POST /embed/leads`.

    `ok=True` + `lead_id=None` is the silent-drop case (honeypot
    filled, future spam gates). Real success has both `ok=True` and
    a `lead_id`. The widget treats both as user-visible success so
    bots can't probe for which case they hit.
    """

    ok: bool
    lead_id: uuid.UUID | None = None
    thank_you_url: str | None = None


__all__ = [
    "AvailableCustomField",
    "EmbedKeyIssue",
    "EmbedKeyIssueResponse",
    "EmbedKeyRead",
    "EmbedSubmission",
    "EmbedSubmissionDayBucket",
    "EmbedSubmissionListResponse",
    "EmbedSubmissionOutcomeLiteral",
    "EmbedSubmissionRead",
    "EmbedSubmissionResponse",
    "EmbedSubmissionSummary",
    "SubmissionAttribution",
    "WidgetConfigBranding",
    "WidgetConfigDocument",
    "WidgetConfigField",
    "WidgetConfigPublic",
    "WidgetConfigPublicDocument",
    "WidgetConfigRead",
    "WidgetConfigSpamProtection",
    "WidgetConfigSpamProtectionPublic",
    "WidgetConfigUpdate",
    "WidgetFieldEntity",
    "WidgetFormCreate",
    "WidgetFormListItem",
    "WidgetFormRead",
    "WidgetFormUpdate",
]


# --- Available custom-field listing (Step 10) -----------------------------


class AvailableCustomField(BaseModel):
    """One row in `GET /embed/available-custom-fields` — the custom
    fields (on contact OR lead) the Owner can opt IN to the widget.
    The Settings picker uses this list; selecting a row appends a
    `WidgetConfigField` with `field_source='custom'` and the right
    `entity` to the widget config.
    """

    entity: WidgetFieldEntity
    field_key: str
    field_label: str
    field_type: str
    is_required: bool
    options: list[str] | None = None
    widget_supported: bool


# --- Widget Config schemas (Step 3) -------------------------------------

# Standard field keys — the 5 baked-in fields the widget always knows
# how to render and route. Custom fields use arbitrary string keys
# matched against the org's `custom_field_definitions` table.
WidgetStandardFieldKey = Literal["full_name", "phone", "email", "interest", "notes"]

_STANDARD_FIELD_KEYS: set[str] = {
    "full_name",
    "phone",
    "email",
    "interest",
    "notes",
}

# v1 supported field types. `number` and `date` were added when custom
# fields landed on the widget — they're common shapes for things like
# budget, preferred-delivery-date custom fields. Adding `multiselect`
# or `file` requires both a bundle bump AND a renderer extension.
WidgetFieldType = Literal["text", "email", "tel", "textarea", "select", "number", "date"]

# Where a widget field's value gets routed at submission time.
#   - "standard": one of the 5 baked-in keys → top-level payload field
#     → contact's standard column (full_name / phone / email) or notes.
#   - "custom":  free-form key → submission's `custom_data[key]` →
#     contact's `custom_data` JSONB.
# Owner opts custom fields IN explicitly via Settings → Embed widget —
# default state is "no custom fields visible to widget visitors" so
# internal-only fields can't leak.
WidgetFieldSource = Literal["standard", "custom"]


# Which entity a custom-source field belongs to. Contact is the default
# for back-compat with widget configs saved before this field existed.
# Lead is for fields like "company name" or "budget" that conceptually
# attach to the opportunity rather than the person submitting it.
WidgetFieldEntity = Literal["contact", "lead"]


class WidgetConfigField(BaseModel):
    """One configurable field in the rendered widget form.

    `options` is required when `field_type='select'`; ignored otherwise.
    The submission service enforces: every submitted value must come
    from `options` if the field is select-typed.

    For `field_source='standard'`, `key` must be one of the 5 baked-in
    field keys (`full_name`, `phone`, `email`, `interest`, `notes`) and
    `entity` is ignored (standard fields always land on the contact).

    For `field_source='custom'`, `key` references a custom field defined
    in the org's `custom_field_definitions` table for the entity given
    by `entity` (`contact` or `lead`). Validation that the referenced
    field actually exists happens at `PUT /embed/config` time.
    """

    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    placeholder: str | None = Field(default=None, max_length=128)
    required: bool = False
    order: int = Field(default=0, ge=0, le=999)
    field_type: WidgetFieldType = "text"
    options: list[str] | None = Field(default=None, max_length=50)
    field_source: WidgetFieldSource = "standard"
    entity: WidgetFieldEntity = "contact"

    @model_validator(mode="after")
    def _check_invariants(self) -> WidgetConfigField:
        """Cross-field invariants:

        1. Select fields MUST have non-empty options; non-select fields
           MUST NOT carry options. Using a model_validator rather than a
           field_validator on `options` because Pydantic v2 skips field
           validators on default values — and `options=None` is the
           default we need to reject when paired with select.
        2. `field_source='standard'` keys must be one of the 5 baked-in
           field keys. (Custom-source keys are free-form here — the
           config-update service validates them against the org's
           defined custom fields at PUT time.)
        """
        if self.field_type == "select":
            if not self.options:
                raise ValueError("field_type='select' requires a non-empty options list")
        else:
            if self.options:
                raise ValueError(
                    f"options are only allowed for field_type='select', not '{self.field_type}'"
                )
        if self.field_source == "standard" and self.key not in _STANDARD_FIELD_KEYS:
            raise ValueError(
                f"field_source='standard' requires key in "
                f"{sorted(_STANDARD_FIELD_KEYS)}, got {self.key!r} — "
                f"set field_source='custom' for org-defined fields"
            )
        return self


class WidgetConfigBranding(BaseModel):
    """Visual customisation. The widget bundle exposes these as CSS
    variables (`--fc-primary` etc., wired up in Step 7) so host sites
    can override them too."""

    logo_url: str | None = Field(default=None, max_length=2048)
    accent_color: str = Field(default="#4F46E5", pattern=r"^#[0-9A-Fa-f]{6}$")
    show_powered_by: bool = True


class WidgetConfigSpamProtection(BaseModel):
    """Per-org spam-protection knobs (Step 8). Submitted alongside the
    rest of the widget config; admin endpoints round-trip the full
    shape, the public endpoint projects only `recaptcha_site_key` +
    `min_fill_time_ms` (the secret key MUST stay server-side).

    Defaults: reCAPTCHA off, 2-second min fill time. Honeypot is
    always on — no toggle, no perf cost.
    """

    recaptcha_enabled: bool = False
    recaptcha_site_key: str | None = Field(default=None, max_length=128)
    recaptcha_secret_key: str | None = Field(default=None, max_length=128)
    min_fill_time_ms: int = Field(default=2000, ge=0, le=60000)

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def _check_recaptcha_keys(self) -> WidgetConfigSpamProtection:
        """If reCAPTCHA is enabled, both keys must be set — otherwise
        the gate fails closed on every submission, which silently
        breaks the form for legit users.
        """
        if self.recaptcha_enabled and (
            not self.recaptcha_site_key or not self.recaptcha_secret_key
        ):
            raise ValueError(
                "recaptcha_enabled=true requires both recaptcha_site_key and recaptcha_secret_key"
            )
        return self


class WidgetConfigSpamProtectionPublic(BaseModel):
    """Public projection — what the widget bundle on a customer's
    website needs to render the reCAPTCHA challenge. Crucially does
    NOT include `recaptcha_secret_key` (admin-only, used server-side
    when calling Google's siteverify).
    """

    recaptcha_enabled: bool = False
    recaptcha_site_key: str | None = None
    min_fill_time_ms: int = 2000


class WidgetConfigDocument(BaseModel):
    """The JSONB-persisted shape — used by the admin endpoints. Wraps
    the field list + branding + spam-protection + UX copy in one
    object. The public endpoint projects this through
    `WidgetConfigPublicDocument` to strip the reCAPTCHA secret.
    """

    fields: list[WidgetConfigField] = Field(default_factory=list)
    submit_button_label: str = Field(default="Get a quote", min_length=1, max_length=64)
    thank_you_message: str = Field(
        default="Thanks — we'll reach out shortly.",
        min_length=1,
        max_length=512,
    )
    thank_you_url: str | None = Field(default=None, max_length=2048)
    branding: WidgetConfigBranding = Field(default_factory=WidgetConfigBranding)
    spam_protection: WidgetConfigSpamProtection = Field(default_factory=WidgetConfigSpamProtection)
    # whatsapp-platform-upgrade Step 22 — DPDP consent checkbox.
    # When enabled, the rendered widget shows a required "I agree
    # to receive WhatsApp messages" checkbox above the submit button.
    # The submit handler refuses to POST until the checkbox is
    # ticked. Default `true` so new orgs are DPDP-compliant out of
    # the box; Owners can opt out only after acknowledging the
    # warning copy in the Settings → Widget tab.
    require_whatsapp_consent: bool = Field(default=True)
    whatsapp_consent_label: str = Field(
        default=("I agree to receive WhatsApp messages about my enquiry from this business."),
        min_length=1,
        max_length=512,
    )

    @field_validator("fields")
    @classmethod
    def _unique_field_keys(cls, value: list[WidgetConfigField]) -> list[WidgetConfigField]:
        keys = [f.key for f in value]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate field keys are not allowed")
        return value


class WidgetConfigPublicDocument(BaseModel):
    """Public projection of the document — the secret reCAPTCHA key is
    omitted. Everything else round-trips identically so the widget
    renderer's shape never has to switch on "is this the admin or
    public response".
    """

    fields: list[WidgetConfigField] = Field(default_factory=list)
    submit_button_label: str = "Get a quote"
    # Step 22 — DPDP consent. Mirrored from the admin document; the
    # public widget JS reads both fields to render the checkbox.
    require_whatsapp_consent: bool = True
    whatsapp_consent_label: str = (
        "I agree to receive WhatsApp messages about my enquiry from this business."
    )
    thank_you_message: str = "Thanks — we'll reach out shortly."
    thank_you_url: str | None = None
    branding: WidgetConfigBranding = Field(default_factory=WidgetConfigBranding)
    spam_protection: WidgetConfigSpamProtectionPublic = Field(
        default_factory=WidgetConfigSpamProtectionPublic
    )


class WidgetConfigUpdate(BaseModel):
    """Body for `PUT /embed/config`. Patch-style — only supplied
    top-level fields are touched; omitted ones stay at their current
    value. The full document is validated after merge.
    """

    fields: list[WidgetConfigField] | None = None
    submit_button_label: str | None = Field(default=None, min_length=1, max_length=64)
    thank_you_message: str | None = Field(default=None, min_length=1, max_length=512)
    thank_you_url: str | None = Field(default=None, max_length=2048)
    branding: WidgetConfigBranding | None = None
    spam_protection: WidgetConfigSpamProtection | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class WidgetConfigRead(BaseModel):
    """Admin response. Carries the document + audit metadata."""

    id: uuid.UUID
    org_id: uuid.UUID
    config: WidgetConfigDocument
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class WidgetConfigPublic(BaseModel):
    """Public response — the widget JS bundle's view. No admin
    metadata; just what's needed to render the form. The nested
    `config` uses the public projection so the reCAPTCHA secret
    never reaches a visitor's browser.
    """

    config: WidgetConfigPublicDocument


# --- Multi-form CRUD (Step 2 of the multi-form track) ----------------------


class WidgetFormListItem(ORMModel):
    """Slim projection for ``GET /embed/forms`` — the Settings → Forms
    list needs enough to render each row without hydrating every full
    config document. ``key_count`` is the number of live (non-revoked)
    embed keys pinned to this form; the service populates it via a
    single aggregate query so the list stays a one-round-trip fetch.
    """

    id: uuid.UUID
    name: str
    slug: str
    is_default: bool
    key_count: int
    created_at: datetime
    updated_at: datetime


class WidgetFormRead(ORMModel):
    """Full form read — includes the persisted config document. Used
    by ``GET /embed/forms/{form_id}`` and echoed back from create /
    update / set-default responses."""

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    slug: str
    is_default: bool
    config: WidgetConfigDocument
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class WidgetFormCreate(BaseModel):
    """Body for ``POST /embed/forms``. Name is the only required field.

    ``slug`` is optional — the service derives one from ``name`` when
    omitted (lowercase, non-alnum → ``-``, deduped against existing
    live slugs on the org). Supplied slugs are validated against the
    URL-safe pattern client-side too so a bad slug fails fast with a
    422 rather than a 500 on the DB unique index.

    Newly-created forms carry the same seed config document as the
    legacy per-org widget — Owner edits it via
    ``PUT /embed/forms/{form_id}``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")


class WidgetFormUpdate(BaseModel):
    """Body for ``PUT /embed/forms/{form_id}``. Patch-style — supplied
    fields are updated, omitted fields stay as they are.

    ``is_default`` intentionally lives on a dedicated
    ``POST /embed/forms/{form_id}/set-default`` endpoint, NOT this
    schema — setting a form as default is an atomic swap with the
    previous default and the endpoint boundary makes that
    transactional guarantee obvious to callers.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    # Config patch — same shape as the legacy WidgetConfigUpdate. When
    # None the config document is untouched; when present the patch is
    # merged into the current document and re-validated.
    config: WidgetConfigUpdate | None = None


# --- Submission log (Step 9) ----------------------------------------------


# Mirrors `EmbedSubmissionOutcome` from models.py — duplicated as a
# Literal to avoid importing the SQLAlchemy enum into Pydantic schemas
# (keeps the schema module dependency-free of the ORM).
EmbedSubmissionOutcomeLiteral = Literal[
    "accepted", "rejected_spam", "rate_limited", "invalid_payload"
]


class EmbedSubmissionRead(ORMModel):
    """One row in the paginated list. `lead_id` is set only for
    `outcome='accepted'` rows; the UI surfaces a "View lead" link
    in that column. `ip_hash` is the same 16-hex-char SHA-256
    truncation used everywhere else in the embed module — never
    a raw IP.
    """

    id: uuid.UUID
    key_id: uuid.UUID | None
    lead_id: uuid.UUID | None
    outcome: EmbedSubmissionOutcomeLiteral
    reason: str | None
    ip_hash: str | None
    referrer: str | None
    landing_url: str | None
    created_at: datetime


class EmbedSubmissionListResponse(BaseModel):
    """Envelope for `GET /embed/submissions` — items + total +
    page metadata so the UI can render a "showing 1–25 of N" footer
    without a second round-trip."""

    items: list[EmbedSubmissionRead]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)


class EmbedSubmissionDayBucket(BaseModel):
    """One day's bucket in the summary endpoint's per-day series.
    Used by the stacked bar chart. The `day` is ISO date (UTC)."""

    day: str
    accepted: int = 0
    rejected_spam: int = 0
    rate_limited: int = 0
    invalid_payload: int = 0


class EmbedSubmissionSummary(BaseModel):
    """Response for `GET /embed/submissions/summary` — drives the
    counts card + bar chart at the top of the submission log tab.

    `by_outcome` is the total over the requested window; `by_day`
    is the per-day stacked breakdown (always one entry per day in
    the window, even days with zero submissions, so the chart's
    x-axis is dense).
    """

    range_from: datetime
    range_to: datetime
    by_outcome: dict[EmbedSubmissionOutcomeLiteral, int]
    by_day: list[EmbedSubmissionDayBucket]
