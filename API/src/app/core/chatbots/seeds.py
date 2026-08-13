"""Default chat-bot seeds (``tasks/chatbot-builder`` Step 15).

Three drop-in bots installed on every new org (and back-filled onto
existing orgs by migration ``0195_bf_chatbot_seeds``):

  1. **Welcome Bot** — trigger ``hey / hello / hi / start``. Text-
     button greeting with three routes.
  2. **Lead Qualification Bot** — trigger ``pricing / quote / demo``.
     Asks name + email + use-case → creates a lead → hands off.
  3. **FAQ Router Bot** — trigger ``help``. List message with 5
     common questions; each row branches to a plain-text answer.

All three land as ``status='draft'`` so a fresh org never auto-fires
messages until an Owner reviews + publishes. Graphs are Python
literals (no runtime-computed IDs) so the seed shape is deterministic
across environments + safe to diff.

Idempotent: :func:`install_default_chatbots` checks case-insensitive
``name`` per org and skips already-installed bots. Same guarantee the
workflows seeder makes, so the backfill migration can re-run without
duplication.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.chatbots.models import Chatbot, ChatbotVersion

logger = logging.getLogger(__name__)


_SEED_CATEGORY = "Seeded"


# --- Seed definitions ----------------------------------------------------


_WELCOME_BOT: dict[str, Any] = {
    "name": "Welcome Bot",
    "description": (
        "Greets first-time inbound messages and routes the customer to browse "
        "products, see pricing, or reach a human. Publish when you're ready."
    ),
    "category": _SEED_CATEGORY,
    "priority": 90,
    "trigger_config": {
        "channel": "any",
        "mode": "keyword",
        "keywords": ["hey", "hello", "hi", "start"],
        "regex_pattern": None,
        "case_sensitive": False,
        "first_message_only": False,
    },
    "graph": {
        "nodes": [
            {
                "id": "text_button_welcome",
                "type": "text_button",
                "position": {"x": 100, "y": 100},
                "config": {
                    "body": (
                        "👋 Welcome to {{contact.first_name}}! How can I help today?"
                    ),
                    "buttons": [
                        {"id": "browse", "title": "Browse products"},
                        {"id": "pricing", "title": "See pricing"},
                        {"id": "human", "title": "Talk to sales"},
                    ],
                },
            },
            {
                "id": "handoff_sales",
                "type": "handoff_to_human",
                "position": {"x": 100, "y": 400},
                "config": {
                    "assign_mode": "specific",
                    "user_id": None,
                    "final_bot_message": (
                        "A team member will jump in shortly — usually within 15 minutes."
                    ),
                },
            },
        ],
        "edges": [
            {
                "id": "e_welcome_human",
                "source": "text_button_welcome",
                "target": "handoff_sales",
                "label": "human",
            },
        ],
    },
}


_LEAD_QUALIFICATION_BOT: dict[str, Any] = {
    "name": "Lead Qualification Bot",
    "description": (
        "Captures name + email + use-case for pricing/demo enquiries, then "
        "creates a lead + hands off to sales. Set your sales assignee before "
        "publishing."
    ),
    "category": _SEED_CATEGORY,
    "priority": 95,
    "trigger_config": {
        "channel": "any",
        "mode": "keyword",
        "keywords": ["pricing", "quote", "demo"],
        "regex_pattern": None,
        "case_sensitive": False,
        "first_message_only": False,
    },
    "graph": {
        "nodes": [
            {
                "id": "ask_name",
                "type": "ask_question",
                "position": {"x": 100, "y": 100},
                "config": {
                    "prompt": "Great! I'd love to help. What's your name?",
                    "save_to": "contact.full_name",
                    "expected_format": "text",
                    "max_retries": 2,
                    "timeout_seconds": 79200,
                    "retry_message": "Sorry, could you share your name?",
                },
            },
            {
                "id": "ask_email",
                "type": "ask_question",
                "position": {"x": 100, "y": 340},
                "config": {
                    "prompt": "Thanks {{answers.ask_name}}! What's your work email?",
                    "save_to": "contact.email",
                    "expected_format": "email",
                    "max_retries": 2,
                    "timeout_seconds": 79200,
                    "retry_message": "That doesn't look like a valid email — try again?",
                },
            },
            {
                "id": "ask_use_case",
                "type": "ask_question",
                "position": {"x": 100, "y": 580},
                "config": {
                    "prompt": "One last thing — what are you trying to solve?",
                    "save_to": "contact.custom.use_case",
                    "expected_format": "text",
                    "max_retries": 1,
                    "timeout_seconds": 79200,
                    "retry_message": "Any short description works — we'll follow up either way.",
                },
            },
            {
                "id": "create_lead",
                "type": "create_lead",
                "position": {"x": 100, "y": 820},
                "config": {
                    "source": "chatbot:lead_qualification",
                    "pipeline_stage": None,
                    "custom_field_map": {
                        "use_case": "answers.ask_use_case",
                    },
                },
            },
            {
                "id": "handoff_sales",
                "type": "handoff_to_human",
                "position": {"x": 100, "y": 1060},
                "config": {
                    "assign_mode": "specific",
                    "user_id": None,
                    "final_bot_message": (
                        "Thanks! A sales rep will reach out within one business day."
                    ),
                },
            },
        ],
        "edges": [
            {
                "id": "e_name_email",
                "source": "ask_name",
                "target": "ask_email",
                "label": "answered",
            },
            {
                "id": "e_email_use_case",
                "source": "ask_email",
                "target": "ask_use_case",
                "label": "answered",
            },
            {
                "id": "e_use_case_lead",
                "source": "ask_use_case",
                "target": "create_lead",
                "label": "answered",
            },
            {
                "id": "e_lead_handoff",
                "source": "create_lead",
                "target": "handoff_sales",
                "label": "created",
            },
        ],
    },
}


_FAQ_ROUTER_BOT: dict[str, Any] = {
    "name": "FAQ Router Bot",
    "description": (
        "Sends a list of the 5 most-asked questions when the customer types "
        "'help'. Edit the row labels to match your business's real FAQ."
    ),
    "category": _SEED_CATEGORY,
    "priority": 80,
    "trigger_config": {
        "channel": "any",
        "mode": "keyword",
        "keywords": ["help"],
        "regex_pattern": None,
        "case_sensitive": False,
        "first_message_only": False,
    },
    "graph": {
        "nodes": [
            {
                "id": "faq_list",
                "type": "list",
                "position": {"x": 100, "y": 100},
                "config": {
                    "body": "How can I help? Pick a topic:",
                    "button_text": "Choose a topic",
                    "sections": [
                        {
                            "title": "Common questions",
                            "rows": [
                                {"id": "pricing", "title": "See pricing"},
                                {"id": "hours", "title": "Business hours"},
                                {"id": "delivery", "title": "Delivery info"},
                                {"id": "returns", "title": "Returns policy"},
                                {"id": "human", "title": "Talk to a human"},
                            ],
                        },
                    ],
                },
            },
            {
                "id": "handoff",
                "type": "handoff_to_human",
                "position": {"x": 100, "y": 500},
                "config": {
                    "assign_mode": "specific",
                    "user_id": None,
                    "final_bot_message": "Connecting you to a teammate.",
                },
            },
        ],
        "edges": [
            {
                "id": "e_faq_human",
                "source": "faq_list",
                "target": "handoff",
                "label": "human",
            },
        ],
    },
}


_ALL_SEEDS: tuple[dict[str, Any], ...] = (
    _WELCOME_BOT,
    _LEAD_QUALIFICATION_BOT,
    _FAQ_ROUTER_BOT,
)


# --- Installer -----------------------------------------------------------


async def install_default_chatbots(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Install the three default bots on ``org_id``. Idempotent —
    bots whose (case-insensitive) name already exists in the org
    are skipped. Returns ``{installed, skipped}`` counts.

    Called from :func:`core.tenants.service.create_organization` on
    new-org boot, and from :mod:`alembic.versions.0195_bf_chatbot_seeds`
    to backfill every existing tenant. Same soft-fail contract as
    the workflows seeder — one bad seed doesn't roll back the rest
    of org creation.
    """
    existing_names = {
        (row[0] or "").lower()
        for row in (
            await session.execute(
                select(Chatbot.name).where(Chatbot.org_id == org_id)
            )
        ).all()
    }

    installed = 0
    skipped = 0
    for seed in _ALL_SEEDS:
        if (seed["name"] or "").lower() in existing_names:
            skipped += 1
            continue
        try:
            bot = Chatbot(
                org_id=org_id,
                name=seed["name"],
                description=seed["description"],
                category=seed.get("category") or _SEED_CATEGORY,
                folder_id=None,
                status="draft",
                priority=int(seed.get("priority") or 100),
                trigger_config=seed["trigger_config"],
                graph=seed["graph"],
                version_number=1,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
            )
            session.add(bot)
            await session.flush()

            session.add(
                ChatbotVersion(
                    org_id=org_id,
                    chatbot_id=bot.id,
                    version_number=1,
                    graph=seed["graph"],
                    trigger_config=seed["trigger_config"],
                    change_note="seeded",
                    created_by_user_id=user_id,
                )
            )
            await session.flush()
            installed += 1
        except Exception:
            logger.exception(
                "chatbots.seeds.install_failed org=%s bot=%s",
                org_id,
                seed["name"],
            )

    if installed:
        await session.commit()

    logger.info(
        "chatbots.seeds.install_done org=%s installed=%d skipped=%d",
        org_id,
        installed,
        skipped,
    )
    return {"installed": installed, "skipped": skipped}


async def count_installed(
    session: AsyncSession, *, org_id: uuid.UUID
) -> int:
    """How many seeded (category=Seeded) bots the org already has —
    used by the backfill migration to short-circuit."""
    stmt = (
        select(func.count())
        .select_from(Chatbot)
        .where(Chatbot.org_id == org_id, Chatbot.category == _SEED_CATEGORY)
    )
    return int((await session.execute(stmt)).scalar_one())


__all__ = [
    "count_installed",
    "install_default_chatbots",
]
