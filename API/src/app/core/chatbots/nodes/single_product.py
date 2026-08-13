"""Single Product node — v1 stub (``tasks/chatbot-builder`` Step 7).

Same shape as :mod:`catalog_message` — visible in the palette,
runtime deferred to the WA Commerce track.
"""

from __future__ import annotations

from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "single_product"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    return _shared.errored_result(
        "single_product requires WA Business Commerce — configure the "
        "catalog first (follow-up WA Commerce track)."
    )


register_node(_NODE_TYPE, handle)
