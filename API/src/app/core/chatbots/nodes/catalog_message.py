"""Catalog Message node — v1 stub (``tasks/chatbot-builder`` Step 7).

Visible in the palette + carryable on a bot graph, but runtime is
gated on WhatsApp Business Commerce (Meta Commerce Manager) which
lands in a future WA Commerce track. The handler errors cleanly so
operators see the empty-state reason instead of a silent no-op.
"""

from __future__ import annotations

from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "catalog_message"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    return _shared.errored_result(
        "catalog_message requires a WA Business Commerce catalog — "
        "configure via Meta Commerce Manager first (follow-up WA "
        "Commerce track)."
    )


register_node(_NODE_TYPE, handle)
