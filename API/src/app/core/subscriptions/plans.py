"""Plan registry — Pydantic-validated reader over `plans.yaml`.

`plans.yaml` is the single source of truth for subscription tiers,
caps, feature flags, and prices. This module loads it once on import,
validates strictly (unknown feature keys are rejected, prices are
converted from display USD to integer cents), and exposes typed
helpers for the rest of the codebase to consume.

Why YAML-on-disk and not Python constants:
  - non-engineers can change pricing without code review
  - one file is the diff for any price/cap/feature edit
  - the future furniture-pack pricing (`packs/furniture/pricing.yaml`)
    follows the same schema and composes on top

Consumers MUST NOT mutate the returned `Plan` objects. They are frozen
Pydantic models; tests that need to override values should call
`reload(path=...)` against a fixture YAML.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Every feature key permitted to appear under `features:` in any plan.
# Adding a new key requires updating both this set and the YAML for every
# plan that should grant it. Missing keys default to `False` at load
# time; unknown keys cause a validation error at boot.
KNOWN_FEATURE_KEYS: frozenset[str] = frozenset(
    {
        "contacts.read",
        "contacts.write",
        "leads.manual_entry",
        "tasks.read",
        "tasks.write",
        "walkins.read",
        "pipelines.read",
        "automation.workflows",
        "conversations.unified_inbox",
        "integrations.whatsapp",
        "integrations.email_imap_smtp",
        "ads.google_webhook",
        "ads.meta_webhook",
        "calls.recording",
        "campaigns.email",
        "sso.saml",
        "audit.full_log",
        "multi_branch",
        "white_label",
    }
)

# Caps with this value are interpreted as "no limit" by entitlement
# checks. `Cap.is_unlimited(value)` is the canonical comparison.
UNLIMITED_SENTINEL: int = -1

# Resolved at import time relative to this file. Tests can override via
# `reload(path=...)` without monkey-patching.
_DEFAULT_YAML_PATH = Path(__file__).parent / "plans.yaml"


class Cap:
    """Helpers for working with the -1 = unlimited convention."""

    @staticmethod
    def is_unlimited(value: int) -> bool:
        return value == UNLIMITED_SENTINEL


class PlanPricing(BaseModel):
    """Bundle + overage pricing for one plan, in display USD."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    monthly_bundle_usd: int = Field(ge=0)
    annual_bundle_usd: int = Field(ge=0)
    included_seats: int = Field(ge=1)
    extra_seat_monthly_usd: int = Field(ge=0)
    extra_seat_annual_usd: int = Field(ge=0)

    @property
    def monthly_bundle_cents(self) -> int:
        return self.monthly_bundle_usd * 100

    @property
    def annual_bundle_cents(self) -> int:
        return self.annual_bundle_usd * 100

    @property
    def extra_seat_monthly_cents(self) -> int:
        return self.extra_seat_monthly_usd * 100

    @property
    def extra_seat_annual_cents(self) -> int:
        return self.extra_seat_annual_usd * 100


class PlanCaps(BaseModel):
    """Numeric caps for one plan. -1 = unlimited (see `Cap.is_unlimited`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contacts: int
    leads_per_month: int
    storage_mb: int
    pipelines: int
    custom_fields_per_entity: int
    form_widgets: int
    form_submissions_per_month: int
    automation_runs_per_month: int
    api_calls_per_day: int
    branches: int
    email_sends_per_month: int
    sms_sends_per_month: int

    @field_validator(
        "contacts",
        "leads_per_month",
        "storage_mb",
        "pipelines",
        "custom_fields_per_entity",
        "form_widgets",
        "form_submissions_per_month",
        "automation_runs_per_month",
        "api_calls_per_day",
        "branches",
        "email_sends_per_month",
        "sms_sends_per_month",
    )
    @classmethod
    def _ge_minus_one(cls, v: int) -> int:
        if v < UNLIMITED_SENTINEL:
            raise ValueError(
                f"cap must be >= 0 (positive integer) or {UNLIMITED_SENTINEL} for unlimited; got {v}"
            )
        return v


class PlanFeatures(BaseModel):
    """Boolean entitlement flags. Unknown keys reject; missing keys default False."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Explicit declarations so missing YAML keys default to False and
    # unknown YAML keys raise (per `extra='forbid'`).
    contacts_read: bool = Field(False, alias="contacts.read")
    contacts_write: bool = Field(False, alias="contacts.write")
    leads_manual_entry: bool = Field(False, alias="leads.manual_entry")
    tasks_read: bool = Field(False, alias="tasks.read")
    tasks_write: bool = Field(False, alias="tasks.write")
    walkins_read: bool = Field(False, alias="walkins.read")
    pipelines_read: bool = Field(False, alias="pipelines.read")
    automation_workflows: bool = Field(False, alias="automation.workflows")
    conversations_unified_inbox: bool = Field(False, alias="conversations.unified_inbox")
    integrations_whatsapp: bool = Field(False, alias="integrations.whatsapp")
    integrations_email_imap_smtp: bool = Field(False, alias="integrations.email_imap_smtp")
    ads_google_webhook: bool = Field(False, alias="ads.google_webhook")
    ads_meta_webhook: bool = Field(False, alias="ads.meta_webhook")
    calls_recording: bool = Field(False, alias="calls.recording")
    campaigns_email: bool = Field(False, alias="campaigns.email")
    sso_saml: bool = Field(False, alias="sso.saml")
    audit_full_log: bool = Field(False, alias="audit.full_log")
    multi_branch: bool = Field(False, alias="multi_branch")
    white_label: bool = Field(False, alias="white_label")

    def has(self, feature_key: str) -> bool:
        """Look up by dotted key (`'automation.workflows'`).

        Unknown keys return False (logged via the entitlement service,
        not here — keeping this method pure).
        """
        if feature_key not in KNOWN_FEATURE_KEYS:
            return False
        return getattr(self, _alias_to_attr(feature_key))

    def as_dict(self) -> dict[str, bool]:
        """Dotted-key view for JSON serialization."""
        return {key: getattr(self, _alias_to_attr(key)) for key in KNOWN_FEATURE_KEYS}


def _alias_to_attr(feature_key: str) -> str:
    return feature_key.replace(".", "_")


class Plan(BaseModel):
    """One subscription tier."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    display_order: int = Field(ge=0)
    is_public: bool
    trial_duration_days: int = Field(ge=0)
    pricing: PlanPricing
    caps: PlanCaps
    features: PlanFeatures

    def serialize(self) -> dict:
        """Public JSON shape — features flattened into dotted keys."""
        return {
            "code": self.code,
            "name": self.name,
            "display_order": self.display_order,
            "is_public": self.is_public,
            "trial_duration_days": self.trial_duration_days,
            "pricing": self.pricing.model_dump(),
            "caps": self.caps.model_dump(),
            "features": self.features.as_dict(),
        }


class PlanRegistry(BaseModel):
    """Parsed root of `plans.yaml`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(ge=1)
    currency: str = Field(min_length=3, max_length=3)
    annual_discount_pct: int = Field(ge=0, le=100)
    plans: list[Plan]

    @field_validator("plans")
    @classmethod
    def _unique_codes(cls, plans: list[Plan]) -> list[Plan]:
        codes = [p.code for p in plans]
        if len(codes) != len(set(codes)):
            duplicates = {c for c in codes if codes.count(c) > 1}
            raise ValueError(f"duplicate plan codes: {sorted(duplicates)}")
        return plans


# ---------------------------------------------------------------------------
# Module-level cache + helpers
# ---------------------------------------------------------------------------

_registry: PlanRegistry | None = None


def _load_from_path(path: Path) -> PlanRegistry:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if raw is None:
        raise ValueError(f"plans.yaml at {path} is empty")
    return PlanRegistry.model_validate(raw)


def reload(path: Path | None = None) -> PlanRegistry:
    """Reload the registry from disk. Used by tests; not needed in prod.

    The first call at import time uses the default path. Subsequent
    `reload()` calls without arguments re-read the same default path —
    useful if the YAML was edited and the process kept warm.
    """
    global _registry
    _registry = _load_from_path(path or _DEFAULT_YAML_PATH)
    # Bust the cached helpers too.
    _by_code_cache.cache_clear()
    _public_sorted_cache.cache_clear()
    return _registry


def registry() -> PlanRegistry:
    """Return the cached registry, loading on first access."""
    global _registry
    if _registry is None:
        _registry = _load_from_path(_DEFAULT_YAML_PATH)
    return _registry


@lru_cache(maxsize=1)
def _by_code_cache() -> dict[str, Plan]:
    return {p.code: p for p in registry().plans}


@lru_cache(maxsize=1)
def _public_sorted_cache() -> list[Plan]:
    return sorted(
        (p for p in registry().plans if p.is_public),
        key=lambda p: p.display_order,
    )


def all() -> list[Plan]:  # noqa: A001 — mirrors the spec'd surface
    """Every plan in the registry, in `display_order` ascending."""
    return sorted(registry().plans, key=lambda p: p.display_order)


def get(code: str) -> Plan | None:
    """Look up a plan by code, including non-public plans (`trial`)."""
    return _by_code_cache().get(code)


def public() -> list[Plan]:
    """Public plans only, in display order. Trial is excluded."""
    return _public_sorted_cache()


def currency() -> str:
    return registry().currency


def annual_discount_pct() -> int:
    return registry().annual_discount_pct


# Eagerly load at import so a malformed YAML refuses process boot
# rather than failing at first request.
registry()
