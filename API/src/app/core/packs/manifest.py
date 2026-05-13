"""Pydantic v2 schema for `pack.yaml`.

A pack manifest is the source of truth (rule 7) for every default a
vertical pack ships:

  - pipelines + stages (kanban defaults — leads, custom_orders, …)
  - custom field definitions (source=`pack`)
  - roles + their permission lists
  - lead sources (config values)
  - call outcomes (config values)
  - org defaults (currency, tax_rate, timezone, AI personality, …)
  - follow-up schedule (Phase 5 reads this)
  - module → permission key map (so the installer knows which keys
    a role's `permissions: [<module>.*]` shorthand expands to)

The installer reads this manifest and seeds the matching DB rows
idempotently. The schema below enforces:
  - keys are slug-shaped (`[a-z][a-z0-9_]*`)
  - keys are unique within their section
  - exactly one `is_won` stage per pipeline (the pipelines engine
    relies on this for the leaderboard's "won this month" query)
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def _validate_key(value: str, *, field_name: str = "key") -> str:
    if not _KEY_RE.match(value):
        raise ValueError(
            f"{field_name} {value!r} must match [a-z][a-z0-9_-]*"
        )
    return value


def _check_unique_keys(items: list[Any], *, key_attr: str, label: str) -> None:
    seen: set[str] = set()
    for item in items:
        k = getattr(item, key_attr)
        if k in seen:
            raise ValueError(f"duplicate {label} key {k!r}")
        seen.add(k)


class StageManifest(BaseModel):
    """One pipeline stage."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    color: Optional[str] = Field(default=None, max_length=16)
    display_order: int = Field(ge=0)
    is_won: bool = False
    is_lost: bool = False

    @model_validator(mode="after")
    def _check_key(self) -> "StageManifest":
        _validate_key(self.key, field_name="stage.key")
        if self.is_won and self.is_lost:
            raise ValueError(
                f"stage {self.key!r} cannot be both is_won and is_lost"
            )
        return self


class PipelineManifest(BaseModel):
    """One named pipeline with its ordered stages."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    stages: list[StageManifest] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> "PipelineManifest":
        _validate_key(self.key, field_name="pipeline.key")
        _check_unique_keys(self.stages, key_attr="key", label="stage")
        # Ensure exactly one is_won stage (leaderboards depend on this).
        wons = [s for s in self.stages if s.is_won]
        if len(wons) != 1:
            raise ValueError(
                f"pipeline {self.key!r} must have exactly one is_won stage "
                f"(found {len(wons)})"
            )
        return self


class CustomFieldManifest(BaseModel):
    """Pack-shipped custom field definition (source='pack' on insert)."""

    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(min_length=1, max_length=64)
    field_key: str = Field(min_length=1, max_length=64)
    field_label: str = Field(min_length=1, max_length=255)
    field_type: str = Field(min_length=1, max_length=32)
    options: Optional[list[str]] = None
    is_required: bool = False
    is_hidden: bool = False
    display_order: int = Field(default=0, ge=0)
    validation: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def _check_key(self) -> "CustomFieldManifest":
        _validate_key(self.field_key, field_name="custom_field.field_key")
        return self


class RoleManifest(BaseModel):
    """Tenant role + the permission keys it should hold."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    permissions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_key(self) -> "RoleManifest":
        _validate_key(self.key, field_name="role.key")
        return self


class LeadSourceManifest(BaseModel):
    """Per-org lead source row."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    display_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_key(self) -> "LeadSourceManifest":
        _validate_key(self.key, field_name="lead_source.key")
        return self


class CallOutcomeManifest(BaseModel):
    """Per-org call outcome row."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    color: str = Field(default="#6b7280", max_length=32)
    display_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_key(self) -> "CallOutcomeManifest":
        _validate_key(self.key, field_name="call_outcome.key")
        return self


class DefaultsManifest(BaseModel):
    """Org-wide preferences the installer writes to `org_settings`.

    Only applied to orgs whose corresponding fields are still at the
    initial value (`store_name IS NULL` for store_name, etc.) — i.e.
    the installer does NOT overwrite an admin's manual edits.
    """

    model_config = ConfigDict(extra="forbid")

    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    tax_rate: Optional[Decimal] = Field(default=None, ge=0, le=100)
    timezone: Optional[str] = Field(default=None, max_length=64)
    locale: Optional[str] = Field(default=None, max_length=16)
    review_source: Optional[str] = Field(default=None, max_length=32)
    ai_personality: Optional[str] = None
    ai_welcome_message: Optional[str] = None


class FollowUpManifest(BaseModel):
    """One row in the follow-up schedule (Phase 5 reads this)."""

    model_config = ConfigDict(extra="forbid")

    day_offset: int = Field(ge=0)
    channel: str = Field(min_length=1, max_length=32)
    template: str = Field(min_length=1, max_length=4096)


class PackManifest(BaseModel):
    """Top-level pack.yaml shape."""

    model_config = ConfigDict(extra="forbid")

    pack_id: str = Field(min_length=1, max_length=32)
    version: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=128)

    pipelines: list[PipelineManifest] = Field(default_factory=list)
    custom_fields: list[CustomFieldManifest] = Field(default_factory=list)
    roles: list[RoleManifest] = Field(default_factory=list)
    lead_sources: list[LeadSourceManifest] = Field(default_factory=list)
    call_outcomes: list[CallOutcomeManifest] = Field(default_factory=list)
    defaults: DefaultsManifest = Field(default_factory=DefaultsManifest)
    follow_up_schedule: list[FollowUpManifest] = Field(default_factory=list)
    # Optional shorthand: module_id -> list of perm keys. Lets a role's
    # `permissions: [staff.*]` expand to the module's full set via
    # the installer (Phase 4.2 fills this).
    module_permissions: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "PackManifest":
        _validate_key(self.pack_id, field_name="pack_id")
        _check_unique_keys(self.pipelines, key_attr="key", label="pipeline")
        _check_unique_keys(self.roles, key_attr="key", label="role")
        _check_unique_keys(
            self.lead_sources, key_attr="key", label="lead_source"
        )
        _check_unique_keys(
            self.call_outcomes, key_attr="key", label="call_outcome"
        )
        # custom_fields uniqueness: (entity_type, field_key)
        seen: set[tuple[str, str]] = set()
        for cf in self.custom_fields:
            pair = (cf.entity_type, cf.field_key)
            if pair in seen:
                raise ValueError(
                    f"duplicate custom_field {pair!r}"
                )
            seen.add(pair)
        return self


__all__ = [
    "CallOutcomeManifest",
    "CustomFieldManifest",
    "DefaultsManifest",
    "FollowUpManifest",
    "LeadSourceManifest",
    "PackManifest",
    "PipelineManifest",
    "RoleManifest",
    "StageManifest",
]
