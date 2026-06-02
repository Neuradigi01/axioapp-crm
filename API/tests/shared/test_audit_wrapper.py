"""Unit tests for `log_entity_change`.

The wrapper is a thin keyword-only pass-through to `audit.log`. These
tests pin its contract by mocking `audit.log` and verifying the
arguments forwarded — no DB round-trip required.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.app.shared.audit import log_entity_change


@pytest.fixture
def fake_audit_log():
    with patch("src.app.shared.audit.helpers.audit.log", new_callable=AsyncMock) as m:
        yield m


async def test_forwards_action_as_positional_arg(fake_audit_log: AsyncMock) -> None:
    """audit.log accepts ``action`` positionally; the wrapper must
    preserve that to avoid silently breaking event-name conventions
    (e.g. dashboards filtering on `action="contacts.created"`)."""

    entity_id = uuid.uuid4()
    await log_entity_change(
        action="contacts.created",
        entity_type="contact",
        entity_id=entity_id,
        after={"name": "alpha"},
    )

    fake_audit_log.assert_awaited_once_with(
        "contacts.created",
        entity_type="contact",
        entity_id=entity_id,
        before=None,
        after={"name": "alpha"},
    )


async def test_passes_before_and_after_through(fake_audit_log: AsyncMock) -> None:
    entity_id = uuid.uuid4()
    before = {"name": "old"}
    after = {"name": "new"}

    await log_entity_change(
        action="contacts.updated",
        entity_type="contact",
        entity_id=entity_id,
        before=before,
        after=after,
    )

    fake_audit_log.assert_awaited_once_with(
        "contacts.updated",
        entity_type="contact",
        entity_id=entity_id,
        before=before,
        after=after,
    )


async def test_delete_path_no_after(fake_audit_log: AsyncMock) -> None:
    """Delete events typically carry only ``before``."""

    entity_id = uuid.uuid4()
    await log_entity_change(
        action="contacts.deleted",
        entity_type="contact",
        entity_id=entity_id,
        before={"name": "alpha"},
    )

    fake_audit_log.assert_awaited_once_with(
        "contacts.deleted",
        entity_type="contact",
        entity_id=entity_id,
        before={"name": "alpha"},
        after=None,
    )


async def test_event_name_format_is_unchanged(fake_audit_log: AsyncMock) -> None:
    """The wrapper does NOT derive the action string from entity_type
    — event-name conventions vary (2-segment, 3-segment, singular vs
    plural module names) and existing dashboards depend on the exact
    strings. Three representative shapes."""

    entity_id = uuid.uuid4()

    for action in (
        "contacts.created",
        "leads.scoring_rule.updated",
        "calls.outcome_deleted",
    ):
        fake_audit_log.reset_mock()
        await log_entity_change(
            action=action,
            entity_type="x",
            entity_id=entity_id,
        )
        forwarded_action = fake_audit_log.await_args.args[0]
        assert forwarded_action == action


async def test_signature_is_keyword_only() -> None:
    """All callers must use kwargs — protects against future
    positional drift that would silently swap entity_type and action."""

    entity_id = uuid.uuid4()
    with pytest.raises(TypeError):
        await log_entity_change(  # type: ignore[misc]
            "contacts.created", "contact", entity_id
        )
