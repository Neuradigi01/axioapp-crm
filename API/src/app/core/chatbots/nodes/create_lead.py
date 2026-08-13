"""Create Lead node (``tasks/chatbot-builder`` Step 10).

Creates a lead via :func:`core.leads.service.create_lead`, which
already handles cross-tenant guards + score computation + custom-
field validation. The bot builds the ``LeadCreate`` payload from
the run's ``answers`` + ``contact_id``.

Config shape::

    {
      "source": "chatbot",                   # required — Lead.source label
      "budget_from": "answers.budget",       # optional path resolution
      "expected_close_date_from": "answers.close_date",
      "pipeline_stage": null,                # None → default first stage
      "custom_field_map": {                  # optional answers → lead.custom_data
        "industry": "answers.industry",
        "notes": "answers.notes"
      }
    }

Output ports: ``created`` (default), ``duplicate`` (contact already
has an active lead — best-effort check), ``error`` (payload
rejected by leads service).
"""

from __future__ import annotations

from typing import Any

from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "create_lead"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    source = str(cfg.get("source") or "chatbot")

    if ctx.run.contact_id is None:
        return NodeResult(
            skip_reason="no_contact_on_run",
            output={"reason": "create_lead needs a contact_id on the run"},
        )

    if ctx.is_test:
        return NodeResult(
            next_edge_label="created",
            output={
                "source": source,
                "contact_id": str(ctx.run.contact_id),
                "test_mode": True,
            },
        )

    # Resolve config paths against the run's answers scope.
    def _from_path(path: str | None) -> Any:
        if not path:
            return None
        if not path.startswith("answers."):
            return path  # literal value
        key = path.split(".", 1)[1]
        return ((ctx.run_context or {}).get("answers") or {}).get(key)

    budget = _from_path(cfg.get("budget_from"))
    expected_close = _from_path(cfg.get("expected_close_date_from"))

    custom_data: dict[str, Any] = {}
    for field_key, path in (cfg.get("custom_field_map") or {}).items():
        value = _from_path(path)
        if value is not None:
            custom_data[str(field_key)] = value

    try:
        from src.app.core.leads.schemas import LeadCreate
        from src.app.core.leads.service import create_lead as _create_lead_service

        payload = LeadCreate(
            contact_id=ctx.run.contact_id,
            pipeline_stage=cfg.get("pipeline_stage"),
            source=source,
            budget=budget,
            expected_close_date=expected_close,
            custom_data=custom_data,
        )
        lead = await _create_lead_service(
            ctx.session,
            org_id=ctx.run.org_id,
            payload=payload,
            require_all_required=False,  # bot-created leads skip staff-form gates
        )
    except Exception as exc:  # noqa: BLE001
        return NodeResult(
            next_edge_label="error",
            skip_reason="lead_service_rejected",
            output={"error": str(exc), "source": source},
        )

    return NodeResult(
        next_edge_label="created",
        output={
            "lead_id": str(lead.id),
            "contact_id": str(ctx.run.contact_id),
            "source": source,
            "pipeline_stage": lead.pipeline_stage,
        },
    )


register_node(_NODE_TYPE, handle)
