"""Pin tests for the Step-1 workflow action-registry stub.

Covers:

  * ``register_action`` + ``resolve`` returns the same factory output.
  * ``resolve`` on an unknown action raises ``ActionNotRegistered``.
  * Re-registering the same action type overwrites silently (Steps
    7-11 test fixtures depend on this).
  * ``is_registered`` + ``list_registered`` reflect the live state.
  * ``unregister_action`` removes a previously registered handler.
"""

from __future__ import annotations

import pytest

from src.app.core.workflows.actions import (
    ActionNotRegistered,
    _clear_registry_for_tests,
    is_registered,
    list_registered,
    register_action,
    resolve,
    unregister_action,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Wipe the registry between cases so registrations don't bleed."""
    _clear_registry_for_tests()
    yield
    _clear_registry_for_tests()


def test_register_then_resolve_returns_factory_output():
    sentinel = object()

    def factory():
        return sentinel

    register_action("send.email", factory)
    assert resolve("send.email") is sentinel


def test_resolve_unknown_action_raises():
    with pytest.raises(ActionNotRegistered):
        resolve("nope.does_not_exist")


def test_register_overwrites_silently():
    register_action("send.email", lambda: "first")
    register_action("send.email", lambda: "second")
    assert resolve("send.email") == "second"


def test_is_registered_reflects_state():
    assert is_registered("delay.wait") is False
    register_action("delay.wait", lambda: object())
    assert is_registered("delay.wait") is True


def test_list_registered_returns_sorted_keys():
    register_action("send.email", lambda: None)
    register_action("delay.wait", lambda: None)
    register_action("record.update_contact", lambda: None)
    assert list_registered() == [
        "delay.wait",
        "record.update_contact",
        "send.email",
    ]


def test_unregister_action_removes_handler():
    register_action("send.email", lambda: object())
    assert is_registered("send.email") is True
    unregister_action("send.email")
    assert is_registered("send.email") is False
    with pytest.raises(ActionNotRegistered):
        resolve("send.email")
