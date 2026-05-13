"""Pydantic v2 schemas for the OrgSettings module.

`OrgSettingsPatch` enumerates the exact keys the PATCH endpoint will
honour. Anything else in the body is ignored (extra='ignore'). No
sneaky `org_id` / `id` / `created_at` mutations.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class OrgSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID

    store_name: Optional[str]
    logo_url: Optional[str]
    gst_number: Optional[str]
    address_line1: Optional[str]
    address_line2: Optional[str]
    city: Optional[str]
    state: Optional[str]
    postal_code: Optional[str]
    country: Optional[str]
    phone: Optional[str]
    email: Optional[str]

    currency: str
    tax_rate: Decimal
    timezone: str
    locale: str

    ai_enabled: bool
    ai_personality: Optional[str]
    ai_welcome_message: Optional[str]

    reviews_auto_request_enabled: bool
    reviews_auto_request_delay_hours: int

    created_at: datetime
    updated_at: datetime


class OrgSettingsPatch(BaseModel):
    """Whitelisted patch payload. Unknown keys ignored by `extra='ignore'`."""

    model_config = ConfigDict(extra="ignore")

    store_name: Optional[str] = Field(default=None, max_length=255)
    logo_url: Optional[str] = Field(default=None, max_length=512)
    gst_number: Optional[str] = Field(default=None, max_length=32)
    address_line1: Optional[str] = Field(default=None, max_length=255)
    address_line2: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=128)
    state: Optional[str] = Field(default=None, max_length=128)
    postal_code: Optional[str] = Field(default=None, max_length=32)
    country: Optional[str] = Field(default=None, max_length=64)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[str] = Field(default=None, max_length=255)

    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    tax_rate: Optional[Decimal] = Field(default=None, ge=0, le=100)
    timezone: Optional[str] = Field(default=None, max_length=64)
    locale: Optional[str] = Field(default=None, max_length=16)

    ai_enabled: Optional[bool] = None
    ai_personality: Optional[str] = None
    ai_welcome_message: Optional[str] = None

    reviews_auto_request_enabled: Optional[bool] = None
    reviews_auto_request_delay_hours: Optional[int] = Field(
        default=None, ge=0, le=720
    )
