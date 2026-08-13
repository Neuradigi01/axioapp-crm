"""Chatbots — Pabbly-Chatflow-style inbound-message bot module.

A separate module (own sidebar entry, own URL, own tables) from
``core/workflows/``. Where workflows fire on internal CRM events
(``lead.created``, ``appointment.booked``), chatbots fire on inbound
customer messages (``whatsapp.message_received``,
``email.message_received``) and drive a conversational flow with
buttons, questions, and branching — the classic Pabbly Chatflow shape.

Step 1 lands the schema only. Later steps fill in the service, DAL,
router, engine, and 23 node handlers. See
``tasks/chatbot-builder/README.md`` for the full plan.

The runtime concept map:

  * ``Chatbot``            — definition (name, status, ``trigger_config``
                             + ``graph`` JSONB). One trigger per bot
                             (Decision §3).
  * ``ChatbotRun``         — one enrolment per inbound-message-driven
                             conversation. Carries ``context`` JSONB so
                             downstream nodes can read prior answers.
  * ``ChatbotStepRun``     — append-only per-node audit log for
                             diagnostics ("why did this node run?").
  * ``ChatbotMeter``       — per-conversation-per-bot and per-org daily
                             reply counters, backing the runaway guard
                             (Decision §9).
  * ``ChatbotPendingReply`` — signed-email-reply-URL nonce store
                              (Step 11).

Never imports from ``packs/`` (Rule 1). Reuses ``core/workflows``'
``sweep_waits`` primitive at runtime — the only shared dependency.
"""

from __future__ import annotations

# Register models with the shared metadata for Alembic autogenerate
# and pin-test discovery.
from src.app.core.chatbots import models as _models  # noqa: F401
