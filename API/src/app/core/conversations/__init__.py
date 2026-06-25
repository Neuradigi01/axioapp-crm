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
# Step 5 — side-effect import. Importing the email adapter registers
# (a) the `email` ChannelAdapter into `registry.py` and (b) the Step 4
# inbound-handler that routes Gmail / Microsoft `MatchedMessage`s into
# the conversations engine. WhatsApp doesn't follow this pattern
# because its credentials are per-org (resolved at send time); email
# is registered process-wide because the adapter itself is stateless
# (it resolves the per-rep mailbox from `account_id` at send time).
import src.app.core.conversations.adapters.email  # noqa: F401
# Step 12 (template-library) — register the SMS stub adapter so the
# editor / campaign dispatch can resolve a channel for 'sms' without
# crashing with `ChannelNotRegistered`. Sending still fails with
# `SMSNotConfigured` until a real provider lands in the SMS track.
import src.app.core.conversations.adapters.sms  # noqa: F401

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
