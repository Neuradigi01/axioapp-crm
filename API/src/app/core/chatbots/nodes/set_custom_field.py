"""Set Custom Field node (``tasks/chatbot-builder`` Step 9).

Writes a static or variable-interpolated value to a save-target
via :mod:`core.chatbots.save_target_registry` — same allow-list
gate as the Ask-* nodes, so sensitive columns can never be
touched from a bot flow.

Config shape::

    {
      "save_to": "contact.custom.lead_source",
      "value": "WhatsApp Bot - FAQ Router"      # raw or {{template}}
    }
"""

from __future__ import annotations

from src.app.core.chatbots import channel_bridge
from src.app.core.chatbots import save_target_registry as save_targets
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.exceptions import InvalidSaveTarget
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "set_custom_field"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    save_to = str(cfg.get("save_to") or "")
    raw_value = cfg.get("value")

    if not save_to:
        return _shared.errored_result("set_custom_field.save_to is required")
    if raw_value is None:
        return _shared.errored_result("set_custom_field.value is required")

    # Save-time validation belt-and-braces (Case #24: field could
    # have been renamed since the graph was authored).
    if not save_to.startswith("run_variable."):
        try:
            await save_targets.validate_save_target(
                ctx.session, org_id=ctx.run.org_id, qualified_key=save_to
            )
        except InvalidSaveTarget as exc:
            return _shared.errored_result(f"save_to rejected: {exc}")

    # Interpolate variables in the value.
    contact_data = await _shared.load_contact_data(
        ctx.session, contact_id=ctx.run.contact_id
    )
    channel = _shared.channel_of(ctx)
    value_str = channel_bridge.render_variables(
        str(raw_value),
        run_context=ctx.run_context,
        contact_data=contact_data,
        channel=channel,
    )

    if ctx.is_test:
        return NodeResult(
            output={
                "save_to": save_to,
                "value": value_str,
                "test_mode": True,
            }
        )

    save_result: dict = {}
    if save_to.startswith("run_variable."):
        variables = dict((ctx.run_context or {}).get("variables") or {})
        var_name = save_to.split(".", 1)[1]
        variables[var_name] = value_str
        return NodeResult(
            context_patch={"variables": variables},
            output={"save_to": save_to, "value": value_str, "entity": "run_variable"},
        )

    try:
        save_result = await save_targets.write_save_target(
            ctx.session,
            org_id=ctx.run.org_id,
            qualified_key=save_to,
            value=value_str,
            contact_id=ctx.run.contact_id,
            lead_id=ctx.run.lead_id,
        )
        await ctx.session.commit()
    except InvalidSaveTarget as exc:
        return _shared.errored_result(f"set_custom_field write rejected: {exc}")

    return NodeResult(
        output={"save_to": save_to, "value": value_str, "save_result": save_result}
    )


register_node(_NODE_TYPE, handle)
