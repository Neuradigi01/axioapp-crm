"""Pydantic v2 schemas for the OrgSettings module.

`OrgSettingsPatch` enumerates the exact keys the PATCH endpoint will
honour. Anything else in the body is ignored (extra='ignore'). No
sneaky `org_id` / `id` / `created_at` mutations.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import time
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.app.shared.schemas import TimestampedOrgScopedOut
from src.app.shared.validators import (
    ValidationError,
    validate_email,
    validate_phone,
    validate_url,
)

# Same patterns as the frontend's *_RE_SRC constants in
# app/src/app/shared/validators/custom-validators.ts.
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
LOCALE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")
POSTAL_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 -]{1,8}[A-Za-z0-9]$")


def _shared_rule(rule: Callable[[str], str], value: str) -> str:
    """Run a `shared.validators` rule, surfacing its reason as a pydantic
    field error (capitalised for display)."""
    try:
        return rule(value)
    except ValidationError as exc:
        raise ValueError(exc.reason[:1].upper() + exc.reason[1:] + ".") from exc


class OrgSettingsOut(TimestampedOrgScopedOut):
    id: uuid.UUID

    store_name: str | None
    logo_url: str | None
    gst_number: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str | None
    phone: str | None
    email: str | None

    currency: str
    tax_rate: Decimal
    timezone: str
    locale: str

    ai_enabled: bool
    ai_personality: str | None
    ai_welcome_message: str | None

    reviews_auto_request_enabled: bool
    reviews_auto_request_delay_hours: int

    # Template-library Step 4 — review-workflow toggles.
    template_review_mandatory: bool
    template_review_self_approve_allowed: bool

    # Step 6 — lead routing. JSONB shape; v1 honours `{"strategy":
    # "round_robin"}` only. Mutation goes through the dedicated
    # `/api/v1/leads/routing-config` endpoints, not the generic
    # settings PATCH, so the Settings UI can render a specialised
    # editor while still surfacing the value in the read-only profile.
    lead_routing_config: dict[str, Any]

    # tasks/appointment-reminders — configurable reminder offsets.
    appointment_reminder_offsets_minutes: list[int]

    # tasks/workflows Step 12 — compliance gates for marketing
    # sends. Surface on the Settings → Compliance UI section.
    quiet_hours_enabled: bool
    quiet_hours_start: time
    quiet_hours_end: time
    quiet_hours_timezone: str
    frequency_cap_marketing_per_week: int
    frequency_cap_marketing_per_day: int
    transactional_bypass_quiet_hours: bool
    transactional_bypass_frequency_cap: bool
    unsubscribe_link_required_in_marketing_email: bool


class LeadRoutingConfigOut(BaseModel):
    """Dedicated response shape for `GET /api/v1/leads/routing-config`.
    Mirrors the JSONB on `org_settings.lead_routing_config` but with
    a typed `strategy` literal so the frontend can switch on it."""

    strategy: Literal["round_robin"] = "round_robin"


class LeadRoutingConfigUpdate(BaseModel):
    """Request shape for `PUT /api/v1/leads/routing-config`. v1 only
    accepts `strategy="round_robin"` — the surface exists so the
    Settings UI can render the chooser; future strategies slot in
    here without an API break."""

    model_config = ConfigDict(extra="forbid")

    strategy: Literal["round_robin"] = "round_robin"


class OrgSettingsPatch(BaseModel):
    """Whitelisted patch payload. Unknown keys ignored by `extra='ignore'`."""

    model_config = ConfigDict(extra="ignore")

    store_name: str | None = Field(default=None, max_length=255)
    logo_url: str | None = Field(default=None, max_length=512)
    gst_number: str | None = Field(default=None, max_length=32)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    state: str | None = Field(default=None, max_length=128)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)

    currency: str | None = Field(default=None, min_length=3, max_length=3)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    timezone: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=16)

    # Store-profile format rules. Mirrored on the frontend in
    # app/src/app/shared/validators/custom-validators.ts so the form
    # and the API accept exactly the same values. Blank optional text
    # is stored as NULL.
    @field_validator(
        "logo_url",
        "gst_number",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "postal_code",
        "country",
        "phone",
        "email",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("store_name")
    @classmethod
    def _validate_store_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Store name is required.")
        return trimmed

    @field_validator("logo_url")
    @classmethod
    def _validate_logo_url(cls, value: str | None) -> str | None:
        return None if value is None else _shared_rule(validate_url, value)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str | None) -> str | None:
        return None if value is None else _shared_rule(validate_email, value)

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        return None if value is None else _shared_rule(validate_phone, value)

    @field_validator("gst_number")
    @classmethod
    def _validate_gst_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        upper = value.upper()
        if not GSTIN_RE.match(upper):
            raise ValueError("GSTIN must be 15 characters (e.g. 29ABCDE1234F1Z5).")
        return upper

    @field_validator("postal_code")
    @classmethod
    def _validate_postal_code(cls, value: str | None) -> str | None:
        if value is not None and not POSTAL_CODE_RE.match(value):
            raise ValueError("Postal code must be 3–10 letters, digits, spaces or dashes.")
        return value

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str | None) -> str:
        upper = (value or "").strip().upper()
        if not CURRENCY_RE.match(upper):
            raise ValueError("Currency must be a 3-letter ISO code (e.g. INR).")
        return upper

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str | None) -> str:
        name = (value or "").strip()
        try:
            ZoneInfo(name)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Timezone must be an IANA name (e.g. Asia/Kolkata).") from exc
        return name

    @field_validator("locale")
    @classmethod
    def _validate_locale(cls, value: str | None) -> str:
        tag = (value or "").strip()
        if not LOCALE_RE.match(tag):
            raise ValueError("Locale must look like en or en-IN.")
        return tag

    ai_enabled: bool | None = None
    ai_personality: str | None = None
    ai_welcome_message: str | None = None

    reviews_auto_request_enabled: bool | None = None
    reviews_auto_request_delay_hours: int | None = Field(default=None, ge=0, le=720)

    # Template-library Step 4 — review-workflow toggles.
    template_review_mandatory: bool | None = None
    template_review_self_approve_allowed: bool | None = None

    # tasks/workflows Step 12 — compliance gates.
    quiet_hours_enabled: bool | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    quiet_hours_timezone: str | None = Field(default=None, max_length=64)
    frequency_cap_marketing_per_week: int | None = Field(default=None, ge=0, le=1000)
    frequency_cap_marketing_per_day: int | None = Field(default=None, ge=0, le=1000)
    transactional_bypass_quiet_hours: bool | None = None
    transactional_bypass_frequency_cap: bool | None = None
    unsubscribe_link_required_in_marketing_email: bool | None = None

    # tasks/appointment-reminders — configurable reminder offsets.
    # List of positive minute-offsets before ``scheduled_at``. Bounds:
    # 5 min ≤ offset ≤ 30 days (43200 min). Max 10 entries; the list
    # is de-duplicated and sorted descending (long-lead-first) before
    # persist so downstream consumers can rely on a canonical shape.
    appointment_reminder_offsets_minutes: list[int] | None = None

    @field_validator("appointment_reminder_offsets_minutes")
    @classmethod
    def _validate_reminder_offsets(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if len(value) > 10:
            raise ValueError("At most 10 reminder offsets are allowed.")
        cleaned: set[int] = set()
        for entry in value:
            if not isinstance(entry, int) or isinstance(entry, bool):
                raise ValueError("Each offset must be an integer number of minutes.")
            if entry < 5:
                raise ValueError("Reminder offsets must be at least 5 minutes.")
            if entry > 43200:
                raise ValueError("Reminder offsets may not exceed 30 days (43200 minutes).")
            cleaned.add(entry)
        return sorted(cleaned, reverse=True)
