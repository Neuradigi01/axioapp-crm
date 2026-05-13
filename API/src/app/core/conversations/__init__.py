"""Conversations engine — channel-agnostic messaging core.

Re-exports the service entry points (no FastAPI / Pydantic) so other
modules can `from src.app.core.conversations import send_outbound`
without dragging in HTTP-layer deps. The channel adapters live under
`adapters/<channel>.py` and register themselves via `registry.py`.
"""
from src.app.core.conversations.registry import (
    register_channel,
    resolve,
    unregister_channel,
)
from src.app.core.conversations.service import (
    get_conversation,
    list_conversations,
    list_messages,
    patch_conversation,
    receive_webhook,
    send_outbound,
)

__all__ = [
    "get_conversation",
    "list_conversations",
    "list_messages",
    "patch_conversation",
    "receive_webhook",
    "register_channel",
    "resolve",
    "send_outbound",
    "unregister_channel",
]
