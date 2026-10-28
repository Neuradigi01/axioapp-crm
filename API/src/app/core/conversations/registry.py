"""Channel adapter registry — mirrors the module-registry pattern.

A channel adapter is registered once at import time (typically in the
adapter module's import side effects) via `register_channel(...)`. The
service looks up the registered factory by `ConversationChannel` and
constructs an adapter per call. The factory is a zero-argument
callable so adapters that depend on config can lazy-load it.

The registry is a module-level dict — per-process, mirroring how
`module_registry` works for the sidebar. A future multi-worker deploy
that needs cross-process consistency would replace this with a
config-driven map; the call sites would not change.
"""

from __future__ import annotations

from collections.abc import Callable

from src.app.core.conversations.adapters import ChannelAdapter
from src.app.core.conversations.models import ConversationChannel


class ChannelNotRegistered(Exception):
    """Raised when an unknown channel is sent to / received from."""


_factories: dict[ConversationChannel, Callable[[], ChannelAdapter]] = {}


def register_channel(
    channel: ConversationChannel,
    factory: Callable[[], ChannelAdapter],
) -> None:
    _factories[channel] = factory


def unregister_channel(channel: ConversationChannel) -> None:
    """Test helper — drop a previously registered adapter."""
    _factories.pop(channel, None)


def resolve(channel: ConversationChannel) -> ChannelAdapter:
    factory = _factories.get(channel)
    if factory is None:
        raise ChannelNotRegistered(f"no adapter registered for channel '{channel.value}'")
    return factory()


def list_registered() -> list[ConversationChannel]:
    return list(_factories.keys())


__all__ = [
    "ChannelNotRegistered",
    "list_registered",
    "register_channel",
    "resolve",
    "unregister_channel",
]
