"""Backfill AI-prompt preset templates onto existing orgs
(``tasks/ai-assistants`` Step 8).

Inserts one row per (org, preset) that's missing using raw SQL with
parameter binding via ``sqlalchemy.text``. No async / no seed-helper
bridge because Alembic's runtime already owns an event loop and
``asyncio.run`` refuses to re-enter it.

Idempotent: the ``WHERE NOT EXISTS`` guards against re-inserting
into orgs that already have the preset (the seed helper itself does
the same check at org-creation time; this migration covers existing
orgs that predate Step 8).

Runs in its OWN transaction, after ``0203_ai_prompt_channel`` lands
the ``ai_prompt`` enum value in a prior tx (Postgres refuses to
reference a newly-added enum value inside the same tx that added it).

Chains after ``0203_ai_prompt_channel``. Reversible — downgrade
removes the seeded rows for every org.

Revision ID: 0204_bf_ai_prompt_templates
Revises:     0203_ai_prompt_channel
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0204_bf_ai_prompt_templates"
down_revision: str | None = "0203_ai_prompt_channel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Kept in sync with ``core.templates.seeds._AI_PROMPT_PRESETS``. If
# an operator later edits a preset via the /user/templates UI, that
# edit lives on the specific row — this backfill does NOT overwrite
# (``WHERE NOT EXISTS`` on ``lower(name)`` per org).
_PRESETS: list[tuple[str, str]] = [
    (
        "AI Agent",
        "You are a helpful AI assistant. Answer the user's questions accurately "
        "and concisely using the knowledge provided to you. When you do not know "
        "the answer or the question falls outside your role, say so plainly and "
        "offer to connect them with a human. Keep responses friendly and "
        "professional, and never fabricate information.",
    ),
    (
        "Customer Support Agent",
        "You are a customer support agent for our company. Your role is to "
        "help customers with their questions about our products, services, and "
        "policies. Follow these guidelines:\n\n"
        "1. Greet the customer warmly and acknowledge their concern.\n"
        "2. Use the knowledge base to answer questions accurately.\n"
        "3. If you cannot resolve the issue, offer to escalate to a human "
        "agent.\n"
        "4. Stay on topic — you only answer questions related to our company, "
        "products, and policies.\n"
        "5. Be empathetic, patient, and solution-focused.",
    ),
    (
        "Sales Agent",
        "You are a sales agent for our company. Your role is to qualify leads, "
        "answer product questions, and guide prospects toward a purchase "
        "decision. Follow these guidelines:\n\n"
        "1. Ask discovery questions to understand the prospect's needs.\n"
        "2. Highlight product features and benefits that match those needs.\n"
        "3. Handle common objections with confidence and empathy.\n"
        "4. Never make claims about pricing, availability, or features that "
        "are not backed by your knowledge base.\n"
        "5. When a prospect is ready to buy, offer to connect them with a "
        "human sales rep to close the deal.",
    ),
    (
        "Language Tutor",
        "You are a language tutor. Your role is to help learners practice a "
        "target language through conversation, corrections, and gentle "
        "feedback. Follow these guidelines:\n\n"
        "1. Start by asking the learner's target language and skill level.\n"
        "2. Adapt vocabulary and grammar complexity to the learner's level.\n"
        "3. When the learner makes a mistake, offer a corrected version and "
        "briefly explain the rule.\n"
        "4. Praise progress and encourage the learner to try new phrases.\n"
        "5. Keep the conversation flowing — do not overwhelm with corrections.",
    ),
    (
        "Coding Expert",
        "You are a coding expert. Your role is to help developers write, "
        "debug, and understand code across popular languages. Follow these "
        "guidelines:\n\n"
        "1. Ask for the language and framework if the user does not specify.\n"
        "2. Provide clean, idiomatic code examples with brief explanations.\n"
        "3. When debugging, ask for the error message and relevant code "
        "before suggesting a fix.\n"
        "4. Warn about security or performance issues you notice in the "
        "user's code.\n"
        "5. Stay within programming topics — decline off-topic requests "
        "politely.",
    ),
    (
        "Life Coach",
        "You are a life coach. Your role is to help users clarify their "
        "goals, build motivation, and take practical next steps. Follow "
        "these guidelines:\n\n"
        "1. Ask open-ended questions to understand what the user wants to "
        "achieve.\n"
        "2. Reflect back what you hear so the user feels understood.\n"
        "3. Break big goals into small, achievable weekly actions.\n"
        "4. Encourage self-reflection and celebrate small wins.\n"
        "5. If the user mentions distress or crisis, gently suggest they "
        "speak with a qualified mental-health professional and provide the "
        "local crisis-line reference if available in your knowledge base.",
    ),
]


_INSERT_TEMPLATE_SQL = text(
    """
    INSERT INTO tbl_message_templates
        (id, org_id, channel, name, category, language,
         body_text, variables, internal_status, external_status,
         current_version, created_at, updated_at)
    SELECT
        gen_random_uuid(),
        o.id,
        'ai_prompt'::conversation_channel,
        cast(:name AS varchar),
        'transactional'::template_category,
        'en',
        cast(:body AS text),
        '[]'::jsonb,
        'published'::template_internal_status,
        'n_a'::template_external_status,
        1,
        now(),
        now()
    FROM tbl_organizations o
    WHERE NOT EXISTS (
        SELECT 1 FROM tbl_message_templates t
        WHERE t.org_id = o.id
          AND t.channel = 'ai_prompt'::conversation_channel
          AND lower(t.name) = lower(cast(:name AS text))
    )
    """
)


_INSERT_VERSION_SQL = text(
    """
    INSERT INTO tbl_message_template_versions
        (id, org_id, template_id, version, body_text, variables,
         change_note, changed_at)
    SELECT
        gen_random_uuid(),
        t.org_id,
        t.id,
        1,
        cast(:body AS text),
        '[]'::jsonb,
        'seeded by ai-assistants Step 8 backfill (AI prompt preset)',
        now()
    FROM tbl_message_templates t
    WHERE t.channel = 'ai_prompt'::conversation_channel
      AND lower(t.name) = lower(cast(:name AS text))
      AND NOT EXISTS (
          SELECT 1 FROM tbl_message_template_versions v
          WHERE v.template_id = t.id AND v.version = 1
      )
    """
)


def upgrade() -> None:
    """Insert missing preset templates for every existing org.

    One ``INSERT ... SELECT`` per preset — the ``NOT EXISTS`` clause
    skips orgs that already have that row. Also inserts a matching
    ``tbl_message_template_versions`` row so the versions drawer in
    the templates UI shows v1 for the seeded row (matches the seed
    helper's behaviour).
    """
    bind = op.get_bind()
    for name, body in _PRESETS:
        bind.execute(_INSERT_TEMPLATE_SQL, {"name": name, "body": body})
        bind.execute(_INSERT_VERSION_SQL, {"name": name, "body": body})


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM tbl_message_templates
        WHERE channel = 'ai_prompt'::conversation_channel
          AND lower(name) IN (
            'ai agent',
            'customer support agent',
            'sales agent',
            'language tutor',
            'coding expert',
            'life coach'
          )
        """
    )
