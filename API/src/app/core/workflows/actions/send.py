"""Send-action handlers for the workflows engine — Step 7.

Seven handlers, one per channel, all conforming to the
:class:`core.workflows.engine.ActionHandler` shape:

  ``async def handle(session, *, run, step_run, node, context) -> ActionResult``

Each handler:

  1. Resolves the recipient via the
     :mod:`core.workflows.recipients` registry. Missing recipient →
     ``ActionResult(skip_reason='recipient_not_found')``.
  2. Hits the Step-12 compliance gate placeholder
     (:func:`_compliance_check` — currently a no-op). When Step 12
     wires the real check it'll return a skip reason for marketing
     sends blocked by DPDP / quiet hours / frequency cap.
  3. Loads the template referenced by ``node.config.template_id``
     from :mod:`core.templates.data_access`. Missing template →
     ``ActionResult(skip_reason='template_missing')``.
  4. Renders body + subject via the templates module's lenient
     :func:`render` (template-library Step 2).
  5. Ships via the matching channel transport. Email goes through
     :func:`shared.email.get_email_backend`; WhatsApp / SMS /
     Facebook / Instagram / push go through the conversations
     adapter registry; Slack uses the minimal client at
     :mod:`core.integrations.slack`.
  6. Returns ``ActionResult`` with ``output={'channel_message_id',
     'rendered_subject', 'rendered_body'}`` so the run-history view
     can show the exact send.

Errors from the channel transport are caught + persisted as
``skip_reason='channel_error'`` with the error message in
``output['error']`` so the run continues (the engine's outer
exception path is reserved for un-typed runtime crashes; a Slack
500 is a routine outage that we surface to the operator rather
than killing the workflow).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from src.app.core.workflows.actions import register_action
from src.app.core.workflows.recipients import (
    UnknownResolver,
)
from src.app.core.workflows.recipients import (
    resolve as resolve_recipient,
)

logger = logging.getLogger(__name__)


# Legacy UI values shipped before the frontend recipient dropdown was
# aligned with the resolver registry. Rewrites keep old workflow JSON
# resolving without a data migration; new writes use the canonical keys.
_LEGACY_RECIPIENT_ALIASES: dict[str, str] = {
    "workflow.owner.email": "user.email",
    "lead.owner.email": "lead.owner",
}


# --- Internal helpers ---------------------------------------------------


async def _compliance_check(
    session,
    *,
    run,
    node: dict[str, Any],
    recipient: str | None,
    channel: str,
):
    """Step 12 — composite compliance pre-flight.

    Returns one of three :class:`core.workflows.compliance` objects:

      * ``Allow``  — proceed with the send.
      * ``Skip(reason)`` — caller returns
        ``_result_skipped(reason)``.
      * ``Defer(until, reason)`` — caller sets
        ``run.next_step_at = until`` + leaves the run as ``pending``
        so the beat sweep resumes the same node.

    Per-node ``config.category`` (``marketing | transactional |
    service``) overrides the workflow-level marketing flag — lets
    a transactional invoice receipt inside a marketing workflow
    bypass the DPDP / quiet-hours / freq-cap gates per the
    legitimate-interest carve-out."""
    from src.app.core.workflows.compliance import check_send

    cfg = node.get("config") or {}
    category = cfg.get("category", "marketing")
    return await check_send(
        session,
        run=run,
        node=node,
        recipient=recipient,
        channel=channel,
        category=category,
    )


async def _gate_or_skip(
    *,
    session,
    run,
    node: dict[str, Any],
    recipient: str | None,
    channel: str,
):
    """Helper: run the compliance pre-flight + translate the
    decision into either ``None`` (proceed) or an
    :class:`ActionResult` the Send handler returns immediately.

    ``Defer`` self-parks the run by setting ``next_step_at`` and
    leaving ``status='pending'``; the beat sweep at every 60s
    resumes the same node when the wait lands."""
    from src.app.core.workflows.compliance import Allow, Defer, Skip
    from src.app.core.workflows.engine import ActionResult
    from src.app.core.workflows.models import WorkflowRunStatus

    decision = await _compliance_check(
        session,
        run=run,
        node=node,
        recipient=recipient,
        channel=channel,
    )
    if isinstance(decision, Allow):
        return None
    if isinstance(decision, Skip):
        return ActionResult(
            skip_reason=decision.reason,
            output={"skip_reason": decision.reason},
        )
    if isinstance(decision, Defer):
        run.status = WorkflowRunStatus.pending
        run.next_step_at = decision.until
        await session.commit()
        return ActionResult(
            skip_reason=decision.reason,
            output={
                "skip_reason": decision.reason,
                "deferred_until": decision.until.isoformat(),
            },
        )
    return None


async def _maybe_bump_schedule_empty_fires(session, *, run, reason: str) -> None:
    """workflow-scheduling Step 6 — when a scheduled run resolves to
    ``recipient_not_found`` (the closest signal to "audience empty"
    the send layer surfaces), bump the schedule's
    ``consecutive_empty_fires`` counter. When 20 fires in a row hit
    that path, the service deactivates the schedule + emails the
    workflow owner.

    Best-effort — never raises into the send handler. Only fires
    when ``run.trigger_kind == 'schedule'`` (event / manual runs
    don't participate in the counter).
    """
    from src.app.core.workflows.models import TriggerKind
    from src.app.core.workflows.service import (
        CONSECUTIVE_EMPTY_DEACTIVATION_THRESHOLD,
        deactivate_schedule_for_empty_fires,
        increment_consecutive_empty_fires_service,
    )

    if reason != "recipient_not_found":
        return
    trigger_kind = getattr(run, "trigger_kind", None)
    schedule_id = getattr(run, "trigger_source_id", None)
    if trigger_kind != TriggerKind.schedule or schedule_id is None:
        return
    try:
        new_count = await increment_consecutive_empty_fires_service(
            session, org_id=run.org_id, schedule_id=schedule_id
        )
        await session.commit()
        if new_count >= CONSECUTIVE_EMPTY_DEACTIVATION_THRESHOLD:
            await deactivate_schedule_for_empty_fires(
                session, org_id=run.org_id, schedule_id=schedule_id
            )
    except Exception:
        logger.exception(
            "workflows.send empty_fire_bump_failed run=%s schedule=%s",
            getattr(run, "id", None),
            schedule_id,
        )


async def _maybe_reset_schedule_empty_fires(session, *, run) -> None:
    """workflow-scheduling Step 6 — after a successful send from a
    scheduled run, reset the empty-fires counter. Signals the
    schedule is doing something useful; the deactivation threshold
    only trips on CONSECUTIVE empty fires."""
    from src.app.core.workflows.models import TriggerKind
    from src.app.core.workflows.service import reset_consecutive_empty_fires_service

    trigger_kind = getattr(run, "trigger_kind", None)
    schedule_id = getattr(run, "trigger_source_id", None)
    if trigger_kind != TriggerKind.schedule or schedule_id is None:
        return
    try:
        await reset_consecutive_empty_fires_service(
            session, org_id=run.org_id, schedule_id=schedule_id
        )
        await session.commit()
    except Exception:
        logger.exception(
            "workflows.send empty_fire_reset_failed run=%s schedule=%s",
            getattr(run, "id", None),
            schedule_id,
        )


async def _resolve_recipient_or_skip(
    session, *, run, node: dict[str, Any], context: dict[str, Any]
):
    """Pull the recipient string out of the resolver registry +
    return either ``(recipient, None)`` or ``(None, skip_reason)``
    so the caller can early-return cleanly."""
    cfg = node.get("config") or {}
    raw = cfg.get("recipient")
    if isinstance(raw, str) and raw:
        kind = raw
    elif isinstance(raw, dict):
        kind = raw.get("kind")
    else:
        kind = None
    if not isinstance(kind, str) or not kind:
        return None, "recipient_kind_missing"

    # Legacy UI values (shipped before the frontend was aligned with the
    # resolver registry keys). Rewrite in-place so old workflow JSON
    # still resolves; new UI writes the canonical keys directly.
    kind = _LEGACY_RECIPIENT_ALIASES.get(kind, kind)

    try:
        recipient = await resolve_recipient(kind, session, run=run, node=node, context=context)
    except UnknownResolver as exc:
        logger.warning(
            "workflows.send unknown_resolver kind=%s node=%s",
            kind,
            node.get("id"),
        )
        return None, f"unknown_resolver:{exc.name}"

    if not recipient:
        # workflow-scheduling Step 6 — record the empty fire against
        # the parent schedule (if this run was schedule-triggered).
        # Fires deactivation at the CONSECUTIVE_EMPTY_DEACTIVATION_
        # THRESHOLD (README-locked at 20).
        await _maybe_bump_schedule_empty_fires(session, run=run, reason="recipient_not_found")
        return None, "recipient_not_found"
    # Successful recipient resolution — reset the empty-fires
    # counter so a schedule doing useful work isn't deactivated by
    # historical empty fires. Best-effort; a failure here doesn't
    # block the send.
    await _maybe_reset_schedule_empty_fires(session, run=run)
    return recipient, None


async def _load_template(session, *, run, template_id_raw: Any):
    """Resolve the template referenced by the node's config.
    Returns ``(template, None)`` or ``(None, skip_reason)``."""
    if template_id_raw is None:
        return None, "template_id_missing"
    try:
        template_id = (
            template_id_raw
            if isinstance(template_id_raw, uuid.UUID)
            else uuid.UUID(str(template_id_raw))
        )
    except (ValueError, TypeError):
        return None, "template_id_malformed"

    from src.app.core.templates import data_access as templates_da

    template = await templates_da.get_template(session, org_id=run.org_id, template_id=template_id)
    if template is None:
        return None, "template_missing"
    return template, None


def _render_template(template, context: dict[str, Any]) -> tuple[str, str | None]:
    """Lenient render via the templates module's resolver — missing
    variables substitute to empty strings so a slightly-stale
    payload doesn't crash the send."""
    from src.app.core.templates.variables import resolve as render

    rendered_body = render(template.body_text or "", context)
    rendered_subject = render(template.subject, context) if template.subject else None
    return rendered_body, rendered_subject


def _result_sent(
    channel_message_id: str | None,
    rendered_subject: str | None,
    rendered_body: str,
):
    """Build the success ActionResult with the standard output
    shape."""
    from src.app.core.workflows.engine import ActionResult

    return ActionResult(
        output={
            "channel_message_id": channel_message_id,
            "rendered_subject": rendered_subject,
            "rendered_body": rendered_body,
        }
    )


def _result_skipped(reason: str, /, **extra: Any):
    from src.app.core.workflows.engine import ActionResult

    output: dict[str, Any] = dict(extra) if extra else {}
    output["skip_reason"] = reason
    return ActionResult(skip_reason=reason, output=output)


def _result_channel_error(reason: str, error_msg: str):
    """Channel transport failed (Slack outage, WhatsApp 24h-window,
    SMS not configured, …). Persist as skipped with the verbatim
    error so the run-history drawer can show it."""
    from src.app.core.workflows.engine import ActionResult

    return ActionResult(
        skip_reason="channel_error",
        output={
            "skip_reason": reason,
            "error": error_msg,
        },
    )


# --- send.email ---------------------------------------------------------


async def _send_email(session, *, run, step_run, node, context):
    recipient, skip = await _resolve_recipient_or_skip(session, run=run, node=node, context=context)
    if skip is not None:
        return _result_skipped(skip)

    gated = await _gate_or_skip(
        session=session,
        run=run,
        node=node,
        recipient=recipient,
        channel="email",
    )
    if gated is not None:
        return gated

    cfg = node.get("config") or {}
    template, skip = await _load_template(session, run=run, template_id_raw=cfg.get("template_id"))
    if skip is not None:
        return _result_skipped(skip)

    rendered_body, rendered_subject = _render_template(template, context)

    # Step 12 — auto-inject unsubscribe footer when missing on a
    # marketing email send.
    from src.app.core.workflows.compliance import ensure_unsubscribe_link

    rendered_body, footer_injected = await ensure_unsubscribe_link(
        session,
        org_id=run.org_id,
        category=cfg.get("category", "marketing"),
        channel="email",
        body=rendered_body,
    )

    from src.app.shared.email import Email
    from src.app.shared.email.org_sender import resolve_org_sender

    # Org-originated workflow mail flows through the org's own
    # sender identity (SMTP or OAuth) — never the platform Brevo
    # sender. When the org hasn't wired one, skip cleanly (INFO log
    # + skip_reason) so the workflow continues rather than erroring.
    backend = await resolve_org_sender(session, org_id=run.org_id)
    if backend is None:
        logger.info(
            "org_sender_not_configured node=%s run=%s org_id=%s",
            node.get("id"),
            run.id,
            run.org_id,
        )
        return _result_skipped("org_sender_not_configured")

    try:
        await backend.send(
            Email(
                to=recipient,
                subject=rendered_subject or template.name,
                body_text=rendered_body,
                body_html=None,
            )
        )
    except Exception as exc:
        logger.warning(
            "workflows.send.email failed node=%s recipient=%s error=%s",
            node.get("id"),
            recipient,
            exc,
        )
        return _result_channel_error("email_send_failed", str(exc))

    # SMTP-style backends don't return a message id — leave None.
    return _result_sent(None, rendered_subject, rendered_body)


# --- send.whatsapp ------------------------------------------------------


async def _send_whatsapp(session, *, run, step_run, node, context):
    recipient, skip = await _resolve_recipient_or_skip(session, run=run, node=node, context=context)
    if skip is not None:
        return _result_skipped(skip)

    gated = await _gate_or_skip(
        session=session,
        run=run,
        node=node,
        recipient=recipient,
        channel="whatsapp",
    )
    if gated is not None:
        return gated

    cfg = node.get("config") or {}
    template, skip = await _load_template(session, run=run, template_id_raw=cfg.get("template_id"))
    if skip is not None:
        return _result_skipped(skip)

    from src.app.core.conversations.adapters.whatsapp import (
        WhatsAppAdapter,
        WhatsAppNotConnected,
        resolve_whatsapp_adapter,
    )
    from src.app.core.conversations.models import ConversationChannel
    from src.app.core.templates.models import TemplateExternalStatus

    if template.channel != ConversationChannel.whatsapp:
        return _result_skipped("template_channel_mismatch")
    if template.external_status != TemplateExternalStatus.approved:
        return _result_skipped("template_not_approved")
    if not template.is_active:
        return _result_skipped("template_inactive")

    rendered_body, _ = _render_template(template, context)

    try:
        adapter = await resolve_whatsapp_adapter(session)
    except WhatsAppNotConnected as exc:
        return _result_channel_error("whatsapp_not_configured", str(exc))

    try:
        if isinstance(adapter, WhatsAppAdapter):
            # Cloud API only delivers business-initiated messages as
            # approved templates, so send the Meta template with the
            # CRM named variables resolved into positional params.
            ref, rendered_body = await _send_whatsapp_cloud_template(
                session,
                adapter=adapter,
                run=run,
                template=template,
                context=context,
                recipient=recipient,
            )
        else:
            ref = await adapter.send(
                org_id=run.org_id,
                external_id=recipient,
                text=rendered_body,
                attachments=[],
            )
    except Exception as exc:
        logger.warning(
            "workflows.send.whatsapp failed node=%s recipient=%s error=%s",
            node.get("id"),
            recipient,
            exc,
        )
        return _result_channel_error("whatsapp_send_failed", str(exc))

    return _result_sent(getattr(ref, "channel_message_id", None), None, rendered_body)


async def _send_whatsapp_cloud_template(session, *, adapter, run, template, context, recipient):
    """Send an approved central WA template through the Cloud API.
    Returns ``(ref, preview)`` where ``preview`` is the Meta body with
    the positional params substituted."""
    from src.app.core.integrations.whatsapp.meta_variables import (
        resolve_named_body_to_positional_params,
    )
    from src.app.core.templates.service import ensure_wa_extension_row
    from src.app.core.tenants import data_access as tenants_da

    wa_template = await ensure_wa_extension_row(session, template=template)
    org = await tenants_da.get_organization_by_id(session, run.org_id)
    org_data = (
        {"name": org.name or "", "support_email": getattr(org, "support_email", "") or ""}
        if org is not None
        else None
    )
    variables = resolve_named_body_to_positional_params(
        template.body_text, context.get("contact"), org_data
    )
    ref = await adapter.send_template(
        org_id=run.org_id,
        external_id=recipient,
        template_name=wa_template.name,
        language=wa_template.language,
        variables=variables,
        header_type=wa_template.header_type,
        header_text=wa_template.header_text,
    )
    preview = wa_template.body or f"[template: {wa_template.name}]"
    for idx, val in variables.items():
        preview = preview.replace("{{" + str(idx) + "}}", val)
    return ref, preview


# --- send.sms / send.facebook / send.instagram / send.push --------------


def _make_adapter_send(channel_name: str, channel_enum):
    """Factory — the four "shipped via the conversations adapter"
    channels share the same dispatch shape; differences live in
    the channel enum + the friendly error label.
    """

    async def _handler(session, *, run, step_run, node, context):
        recipient, skip = await _resolve_recipient_or_skip(
            session, run=run, node=node, context=context
        )
        if skip is not None:
            return _result_skipped(skip)

        gated = await _gate_or_skip(
            session=session,
            run=run,
            node=node,
            recipient=recipient,
            channel=channel_name,
        )
        if gated is not None:
            return gated

        cfg = node.get("config") or {}
        template, skip = await _load_template(
            session, run=run, template_id_raw=cfg.get("template_id")
        )
        if skip is not None:
            return _result_skipped(skip)

        rendered_body, _ = _render_template(template, context)

        from src.app.core.conversations.registry import (
            ChannelNotRegistered,
        )
        from src.app.core.conversations.registry import (
            resolve as resolve_adapter,
        )

        try:
            adapter = resolve_adapter(channel_enum)
        except ChannelNotRegistered as exc:
            return _result_channel_error(f"{channel_name}_not_configured", str(exc))

        try:
            ref = await adapter.send(
                org_id=run.org_id,
                external_id=recipient,
                text=rendered_body,
                attachments=[],
            )
        except Exception as exc:
            logger.warning(
                "workflows.send.%s failed node=%s recipient=%s error=%s",
                channel_name,
                node.get("id"),
                recipient,
                exc,
            )
            return _result_channel_error(f"{channel_name}_send_failed", str(exc))

        return _result_sent(getattr(ref, "channel_message_id", None), None, rendered_body)

    _handler.__name__ = f"_send_{channel_name}"
    return _handler


# --- send.slack ---------------------------------------------------------


async def _send_slack(session, *, run, step_run, node, context):
    """Slack uses an incoming-webhook URL rather than a channel
    adapter. The node config carries the webhook URL OR a flag
    ``use_org_default`` to look it up from
    ``tbl_integrations.slack_webhook`` (the latter is a future
    enhancement — Step 7 ships the literal-URL path only)."""
    cfg = node.get("config") or {}
    webhook_url = cfg.get("webhook_url")
    if not isinstance(webhook_url, str) or not webhook_url.startswith("https://"):
        return _result_skipped("slack_webhook_missing")

    gated = await _gate_or_skip(
        session=session,
        run=run,
        node=node,
        recipient=webhook_url,
        channel="slack",
    )
    if gated is not None:
        return gated

    template, skip = await _load_template(session, run=run, template_id_raw=cfg.get("template_id"))
    if skip is not None:
        return _result_skipped(skip)

    rendered_body, _ = _render_template(template, context)

    from src.app.core.integrations.slack import (
        SlackError,
        post_message,
    )

    try:
        await post_message(
            webhook_url,
            rendered_body,
            idempotency_key=str(step_run.id) if step_run else None,
        )
    except SlackError as exc:
        return _result_channel_error("slack_send_failed", str(exc))

    return _result_sent(None, None, rendered_body)


# --- Registration -------------------------------------------------------


def register() -> None:
    """Register the seven Send handlers into the action registry.
    Idempotent — the registry's ``register_action`` overwrites on
    duplicate so this is safe to call multiple times."""
    # Local import deferred until registration so the
    # conversations enum is available without forcing an import
    # cycle at module import.
    from src.app.core.conversations.models import ConversationChannel

    register_action("send.email", lambda: _send_email)
    register_action("send.whatsapp", lambda: _send_whatsapp)
    register_action(
        "send.sms",
        lambda: _make_adapter_send("sms", ConversationChannel.sms),
    )
    register_action(
        "send.facebook",
        lambda: _make_adapter_send("facebook", ConversationChannel.facebook),
    )
    register_action(
        "send.instagram",
        lambda: _make_adapter_send("instagram", ConversationChannel.instagram),
    )
    register_action(
        "send.push",
        lambda: _make_adapter_send("push", ConversationChannel.push),
    )
    register_action("send.slack", lambda: _send_slack)


# Side-effect registration on import. The workflows package init
# imports this module so the registry is populated before the
# engine ever dispatches.
register()


__all__ = ["register"]
