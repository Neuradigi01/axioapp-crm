"""Pydantic v2 schemas for users.

`UserOut` is the standard read shape for admin listings.
`UserMe` extends it with the role + permission keys so the frontend
can render gated UI from a single `/users/me` round-trip.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.app.shared.schemas import ORMModel, TimestampedOrgScopedOut


class UserOut(TimestampedOrgScopedOut):
    # `populate_by_name=True` (inherited from ORMModel) lets callers pass
    # `id=...` explicitly alongside the `validation_alias` below, which
    # pulls from `User.legacy_uuid` when `model_validate(user)` reads off
    # the ORM instance. (After DR.6.3 `User.id` is the bigint storage PK;
    # the UUID identity exposed to API consumers is `User.legacy_uuid`.)
    id: uuid.UUID = Field(validation_alias="legacy_uuid")
    # Plain str (not EmailStr): seed uses `admin@demo.local`, which RFC 6761
    # reserves and EmailStr rejects on serialise. Strict email validation
    # lives at create/update boundaries, not on read.
    email: str
    full_name: str
    phone: str | None
    role_id: uuid.UUID
    is_active: bool


class OrgSummary(ORMModel):
    """Compact org identity included in `/users/me` so the SPA can
    brand its shell (sidebar header, etc.) per current tenant without
    a second round-trip."""

    id: uuid.UUID
    name: str
    slug: str
    template_id: str


class UserMe(UserOut):
    role_name: str
    permission_keys: list[str]
    org: OrgSummary
    # `True` while the user's org is in `template_id="pending"` state —
    # i.e. they registered but haven't completed the post-signup
    # onboarding picker. Frontend route guard reads this to redirect
    # to `/onboarding` until it flips to `False`.
    needs_onboarding: bool = False


class UserCreate(BaseModel):
    """Admin creates a new user in the caller's org.

    Password is not set here — the user is unable to log in until they
    accept an invitation (step 2.5.6). A random placeholder password
    is written so the bcrypt verify never short-circuits NULL.
    """

    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    role_id: uuid.UUID


class UserUpdate(BaseModel):
    """Admin updates a user's display name, phone, or role.

    Email is immutable — changing email means inviting a new account.
    Status (is_active) goes through a separate endpoint so the audit
    trail is unambiguous.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    role_id: uuid.UUID | None = None


class UserStatusUpdate(BaseModel):
    is_active: bool


class MeUpdate(BaseModel):
    """Self-service profile update — name + phone only.

    Email is immutable; changing it = inviting a new account. Role and
    org-membership state are admin-only and stay out of this shape.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=255)
    sign_out_others: bool = False


# --- Offboarding / workload shapes -----------------------------------------


_TRANSFER_ENTITIES = ("contacts", "leads", "walk_ins", "appointments", "tasks")


class OpenRecordsCounts(BaseModel):
    """Per-entity open-record counts for one user. `total` is the
    convenience sum the FE renders in the deactivation modal."""

    user_id: uuid.UUID
    contacts: int = 0
    leads: int = 0
    walk_ins: int = 0
    appointments: int = 0
    tasks: int = 0
    total: int = 0


class TransferRecordsRequest(BaseModel):
    """Atomic bulk-reassign for an offboarding user. `entities` lets
    the caller scope to a subset — default is all five. The Pydantic
    validator rejects any unknown entity name."""

    to_user_id: uuid.UUID
    entities: list[str] = Field(default_factory=lambda: list(_TRANSFER_ENTITIES))
    reason: Optional[str] = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)

    @classmethod
    def _validate_entity(cls, name: str) -> str:
        if name not in _TRANSFER_ENTITIES:
            raise ValueError(
                f"unknown entity {name!r}; expected one of {_TRANSFER_ENTITIES}"
            )
        return name

    def normalised_entities(self) -> list[str]:
        if not self.entities:
            raise ValueError("entities must be a non-empty list")
        # Validate + deduplicate while preserving caller order so the
        # transfer summary's per-entity ordering matches the request.
        seen: set[str] = set()
        out: list[str] = []
        for name in self.entities:
            self._validate_entity(name)
            if name not in seen:
                seen.add(name)
                out.append(name)
        return out


class TransferRecordsResponse(BaseModel):
    """Summary of an atomic transfer."""

    from_user_id: uuid.UUID
    to_user_id: uuid.UUID
    transferred: dict[str, int]
    total: int
    audit_activities_written: int


class WorkloadEntry(BaseModel):
    user_id: uuid.UUID
    first_name: str
    last_name: str
    is_active: bool
    counts: OpenRecordsCounts


class WorkloadReport(BaseModel):
    users: list[WorkloadEntry]
    as_of: datetime
