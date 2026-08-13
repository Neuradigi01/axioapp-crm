"""Add Tag node (``tasks/chatbot-builder`` Step 9).

Adds one or more tags to the run's linked contact. Reuses the
existing ``bulk_add_tag_contacts`` helper in
:mod:`core.contacts.service` — Postgres ``array_append`` with a
``= ANY(tags)`` guard makes the operation idempotent (repeat adds
of the same tag don't duplicate).

Config shape::

    {
      "entity": "contact",           # v1: contact only (lead tagging is a follow-up)
      "operation": "add",            # add | remove
      "tags": ["bot-qualified", "interested"]
    }

Missing contact → run continues, no-op; skip_reason recorded.
"""

from __future__ import annotations

from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "add_tag"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    entity = str(cfg.get("entity") or "contact")
    operation = str(cfg.get("operation") or "add")
    tags = cfg.get("tags") or []

    if entity != "contact":
        return _shared.errored_result(
            f"add_tag.entity={entity!r} — v1 supports 'contact' only"
        )
    if operation not in {"add", "remove"}:
        return _shared.errored_result(
            f"add_tag.operation must be add|remove; got {operation!r}"
        )
    if not isinstance(tags, list) or not tags:
        return _shared.errored_result("add_tag.tags must be a non-empty list")

    if ctx.run.contact_id is None:
        return NodeResult(
            skip_reason="no_contact_on_run",
            output={"entity": entity, "operation": operation, "tags": tags},
        )

    if ctx.is_test:
        return NodeResult(
            output={
                "entity": entity,
                "operation": operation,
                "tags": tags,
                "test_mode": True,
            }
        )

    from src.app.core.contacts import service as contacts_service

    applied: list[str] = []
    for tag in tags:
        clean = str(tag).strip()
        if not clean:
            continue
        if operation == "add":
            try:
                await contacts_service.bulk_add_tag_contacts(
                    ctx.session,
                    ids=[ctx.run.contact_id],
                    tag=clean,
                    org_id=ctx.run.org_id,
                )
                applied.append(clean)
            except Exception as exc:  # noqa: BLE001
                return _shared.errored_result(
                    f"add_tag failed for {clean!r}: {exc}"
                )
        else:
            # v1 remove: read-modify-write on the contact's tags
            # array. Batched remove helper is a follow-up.
            from src.app.core.chatbots import data_access as _dal

            contact = await _dal.load_contact_for_bot_write(
                ctx.session, org_id=ctx.run.org_id, contact_id=ctx.run.contact_id
            )
            if contact is None:
                return NodeResult(
                    skip_reason="contact_missing",
                    output={"tags_attempted": tags},
                )
            current = list(contact.tags or [])
            if clean in current:
                current.remove(clean)
                contact.tags = current
                await ctx.session.commit()
                applied.append(clean)

    return NodeResult(
        output={
            "entity": entity,
            "operation": operation,
            "tags_applied": applied,
        }
    )


register_node(_NODE_TYPE, handle)
