"""Single AI Message node — v1 inert stub
(``tasks/chatbot-builder`` Step 10).

Visible in the palette + carryable on a bot graph. The runtime is
gated on ``tbl_organizations.ai_provider_configured`` (migration
``0193_org_ai_provider``), which is FALSE until a future AI-
provider track wires up LLM credentials.

Config shape (accepted at save-time, unused at runtime v1)::

    {
      "system_prompt": "You are a helpful sales assistant for {{org.name}}.",
      "user_prompt_template": "The customer just said: {{run.last_inbound_text}}",
      "max_tokens": 400,
      "temperature": 0.4,
      "save_reply_to": "answers.ai_reply"
    }

Output ports: ``sent`` (once wired), ``error`` (v1: always
``error`` with ``ai_not_configured`` reason).
"""

from __future__ import annotations

from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)

_NODE_TYPE = "single_ai_message"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    # Load org — the ai_provider_configured flag lives on
    # tbl_organizations. Use the tenants DAL (layered — service
    # layer would be overkill for a boolean flag read).
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

    # v1 stub — send-side lands with the AI-provider track.
    return NodeResult(
        next_edge_label="error",
        skip_reason="ai_send_not_implemented",
        output={
            "reason": "single_ai_message runtime deferred to the AI-provider track",
        },
    )


register_node(_NODE_TYPE, handle)
