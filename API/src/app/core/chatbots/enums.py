"""Chatbots ENUMs — lifecycle + trigger classification.

Five PostgreSQL ENUMs are created by migration
``0189_chatbots_init``; the model declarations reference them with
``create_type=False`` so SQLAlchemy doesn't try to CREATE TYPE on
test-DB metadata create.
"""

from __future__ import annotations

import enum

from sqlalchemy.dialects.postgresql import ENUM


class ChatbotStatus(str, enum.Enum):
    """Lifecycle of a bot definition.

    ``draft``    — operator is composing; matcher never fires against a
                   draft.
    ``live``     — published; matcher fires on matching inbound
                   messages. Matches the Pabbly header Draft/Live
                   toggle.
    ``paused``   — temporarily off; parked runs continue but no new
                   enrolments.
    ``archived`` — terminal, hidden from list; can clone but not edit.
    """

    draft = "draft"
    live = "live"
    paused = "paused"
    archived = "archived"


chatbot_status_enum = ENUM(
    ChatbotStatus,
    name="chatbot_status",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class ChatbotRunStatus(str, enum.Enum):
    """Lifecycle of a single enrolment.

    ``running``   — engine is walking the graph.
    ``parked``    — waiting at a wait-for-reply / delay / question
                    node. Resumed by the sweeper or by inbound.
    ``completed`` — reached an end node normally.
    ``canceled``  — human took over, bot archived, cap hit, etc.
                    Reason lives in ``canceled_reason``.
    ``errored``   — a node handler raised.
    """

    running = "running"
    parked = "parked"
    completed = "completed"
    canceled = "canceled"
    errored = "errored"


chatbot_run_status_enum = ENUM(
    ChatbotRunStatus,
    name="chatbot_run_status",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class ChatbotStepStatus(str, enum.Enum):
    """Per-node audit status."""

    pending = "pending"
    running = "running"
    completed = "completed"
    skipped = "skipped"
    errored = "errored"


chatbot_step_status_enum = ENUM(
    ChatbotStepStatus,
    name="chatbot_step_status",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class TriggerMode(str, enum.Enum):
    """How the trigger config matches inbound message text.

    ``any``     — match every inbound (channel filter still applies).
    ``keyword`` — word-boundary match against the ``keywords`` list.
    ``regex``   — google-re2 pattern in ``regex_pattern``.
    """

    any = "any"
    keyword = "keyword"
    regex = "regex"


trigger_mode_enum = ENUM(
    TriggerMode,
    name="chatbot_trigger_mode",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class TriggerChannel(str, enum.Enum):
    """Which inbound channel the trigger listens on."""

    any = "any"
    whatsapp = "whatsapp"
    email = "email"


trigger_channel_enum = ENUM(
    TriggerChannel,
    name="chatbot_trigger_channel",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)
