"""Unit tests for the shared bulk-action schemas.

Pins the request-payload contract that the contacts / leads / tasks
list-page bulk endpoints share:

- ``ids`` is required, non-empty, capped at 200.
- ``BulkReassign.assigned_to_id`` is optional (``None`` clears the
  owner for entities that allow it).
- ``BulkAddTag.tag`` is a non-empty string ≤ 64 chars.

Also verifies that the per-entity aliases (``ContactBulkReassign``,
``LeadBulkReassign``, ``TaskBulkReassign``) resolve to the same
underlying class — so OpenAPI / FE wire shape is identical across
entities.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.app.shared.schemas import (
    BulkAddTag,
    BulkAddTagResult,
    BulkDelete,
    BulkDeleteResult,
    BulkReassign,
    BulkReassignResult,
)


# --- BulkReassign --------------------------------------------------------


def test_bulk_reassign_valid_payload() -> None:
    payload = BulkReassign(
        ids=[uuid.uuid4(), uuid.uuid4()],
        assigned_to_id=uuid.uuid4(),
        note="reassigning batch",
    )
    assert len(payload.ids) == 2
    assert payload.note == "reassigning batch"


def test_bulk_reassign_assigned_to_id_optional() -> None:
    """``None`` is a meaningful value — clears the owner."""
    payload = BulkReassign(ids=[uuid.uuid4()], assigned_to_id=None)
    assert payload.assigned_to_id is None


def test_bulk_reassign_strips_whitespace() -> None:
    """``str_strip_whitespace=True`` is inherited from the shared config."""
    payload = BulkReassign(ids=[uuid.uuid4()], note="  trim me  ")
    assert payload.note == "trim me"


def test_bulk_reassign_note_max_length() -> None:
    with pytest.raises(ValidationError):
        BulkReassign(ids=[uuid.uuid4()], note="x" * 501)


# --- BulkDelete ----------------------------------------------------------


def test_bulk_delete_valid_payload() -> None:
    payload = BulkDelete(ids=[uuid.uuid4()])
    assert len(payload.ids) == 1


# --- BulkAddTag ----------------------------------------------------------


def test_bulk_add_tag_valid_payload() -> None:
    payload = BulkAddTag(ids=[uuid.uuid4()], tag="vip")
    assert payload.tag == "vip"


def test_bulk_add_tag_rejects_empty_tag() -> None:
    with pytest.raises(ValidationError):
        BulkAddTag(ids=[uuid.uuid4()], tag="")


def test_bulk_add_tag_tag_max_length() -> None:
    """64-char cap matches the contacts module's ``_TAG_MAX``."""
    BulkAddTag(ids=[uuid.uuid4()], tag="x" * 64)
    with pytest.raises(ValidationError):
        BulkAddTag(ids=[uuid.uuid4()], tag="x" * 65)


# --- ids constraints (shared via BulkIds base) --------------------------


@pytest.mark.parametrize("schema_cls", [BulkReassign, BulkDelete])
def test_ids_must_be_non_empty(schema_cls) -> None:
    with pytest.raises(ValidationError):
        schema_cls(ids=[])


def test_bulk_add_tag_ids_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        BulkAddTag(ids=[], tag="vip")


def test_ids_capped_at_200() -> None:
    """The per-request cap aligns with the pagination max page size."""
    ids = [uuid.uuid4() for _ in range(200)]
    BulkDelete(ids=ids)  # at the cap — ok

    with pytest.raises(ValidationError):
        BulkDelete(ids=[uuid.uuid4() for _ in range(201)])


# --- Result envelopes ----------------------------------------------------


def test_result_envelopes() -> None:
    assert BulkReassignResult(reassigned=3).reassigned == 3
    assert BulkDeleteResult(deleted=5).deleted == 5
    assert BulkAddTagResult(updated=7).updated == 7


# --- Per-entity aliases resolve to the shared classes -------------------


def test_aliases_resolve_to_shared_classes() -> None:
    """Type aliases collapse `ContactBulkReassign` / `LeadBulkReassign` /
    `TaskBulkReassign` to the same underlying class — so the wire shape
    is uniform across the three list pages."""

    from src.app.core.contacts.schemas import (
        ContactBulkAddTag,
        ContactBulkDelete,
        ContactBulkReassign,
    )
    from src.app.core.leads.schemas import LeadBulkDelete, LeadBulkReassign
    from src.app.core.tasks.schemas import TaskBulkDelete, TaskBulkReassign

    assert ContactBulkReassign is BulkReassign
    assert LeadBulkReassign is BulkReassign
    assert TaskBulkReassign is BulkReassign

    assert ContactBulkDelete is BulkDelete
    assert LeadBulkDelete is BulkDelete
    assert TaskBulkDelete is BulkDelete

    assert ContactBulkAddTag is BulkAddTag
