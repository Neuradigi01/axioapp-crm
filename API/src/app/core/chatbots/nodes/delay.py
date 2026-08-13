"""Delay node (``tasks/chatbot-builder`` Step 9).

Parks the run for a fixed duration; the Step-9 ``sweep_chatbot_waits``
Celery beat picks it up when ``next_step_at <= now()`` and re-
dispatches ``process_step``. On resume the handler simply advances
via the unlabeled default edge.

Config shape::

    {
      "duration_seconds": 300,   # OR {amount: 5, unit: "minutes"}
      "amount": 5,               # optional, alt to duration_seconds
      "unit": "minutes"          # seconds | minutes | hours | days
    }

Max delay capped at 30 days to match the workflows engine's own
wait-node ceiling — anything longer is almost always a config bug.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "delay"
_MAX_DELAY_SECONDS = 30 * 24 * 3600

_UNIT_TO_SECONDS: dict[str, int] = {
    "seconds": 1,
    "minutes": 60,
    "hours": 3600,
    "days": 86400,
}


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    if _shared.is_resumed_from_park(ctx):
        # Sweeper woke us up — advance via the default edge. Clear
        # the resume flag so the NEXT node's handler doesn't see it.
        return NodeResult(context_patch=_shared.clear_resume_flag())

    cfg = ctx.node_config or {}
    seconds = _resolve_duration_seconds(cfg)
    if seconds is None or seconds <= 0:
        return _shared.errored_result(
            "delay.duration_seconds (or {amount, unit}) required and > 0"
        )
    if seconds > _MAX_DELAY_SECONDS:
        return _shared.errored_result(
            f"delay > {_MAX_DELAY_SECONDS}s ({_MAX_DELAY_SECONDS // 86400} days) rejected"
        )

    resume_at = datetime.now(UTC) + timedelta(seconds=seconds)
    ctx.run.next_step_at = resume_at

    return NodeResult(
        park_key=("delay", ctx.node_id),
        context_patch={"delay_until": resume_at.isoformat()},
        output={
            "delayed_seconds": seconds,
            "resume_at": resume_at.isoformat(),
        },
    )


def _resolve_duration_seconds(cfg: dict) -> int | None:
    raw_seconds = cfg.get("duration_seconds")
    if raw_seconds is not None:
        try:
            return int(raw_seconds)
        except (TypeError, ValueError):
            return None

    amount = cfg.get("amount")
    unit = cfg.get("unit")
    if amount is None or unit is None:
        return None
    try:
        amt_int = int(amount)
    except (TypeError, ValueError):
        return None
    multiplier = _UNIT_TO_SECONDS.get(str(unit).lower())
    if multiplier is None:
        return None
    return amt_int * multiplier


register_node(_NODE_TYPE, handle)
