"""Assign AI Assistant node — v1 inert stub
(``tasks/chatbot-builder`` Step 10).

Same shape as :mod:`single_ai_message` — visible in the palette,
gated on the ``ai_provider_configured`` flag, always returns
``error`` in v1 until a real LLM integration lands.

Where ``single_ai_message`` is one-shot, ``assign_ai_assistant``
would hand the conversation over to an ongoing LLM chat (context-
carried across turns, tools invocable). The v1 stub ensures the
palette shows the node + operators can wire it into a graph so
their flow is future-proof.

Config shape (accepted at save-time, unused at runtime v1)::

    {
      "assistant_id": "<external-provider-assistant-id>",
      "system_prompt": "...",
      "max_turns": 8,
      "handoff_on_low_confidence": true
    }

Output ports: ``handed_off`` (once wired), ``error`` (v1: always
``error``).
"""

from __future__ import annotations

from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)

_NODE_TYPE = "assign_ai_assistant"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    from src.app.core.tenants import data_access as tenants_da

    org = await tenants_da.get_organization_by_id(
        ctx.session, ctx.run.org_id
    )
    ai_ready = bool(getattr(org, "ai_provider_configured", False))

    if not ai_ready:
        return NodeResult(
            next_edge_label="error",
            skip_reason="ai_not_configured",
            output={
                "reason": "org.ai_provider_configured is FALSE — configure an "
                          "AI provider in Settings first",
            },
        )

    return NodeResult(
        next_edge_label="error",
        skip_reason="ai_assistant_not_implemented",
        output={
            "reason": "assign_ai_assistant runtime deferred to the AI-provider track",
        },
    )


register_node(_NODE_TYPE, handle)
