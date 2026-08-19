"""AI Assistants — org-scoped BYOK chat assistants
(``tasks/ai-assistants`` Step 5).

Sits in the sidebar's ``Automation`` section between Workflows
(``menu_position=710``) and Chatbots (``menu_position=720``); this
module is ``menu_position=715``.

Concept map:

  * :class:`~core.ai_assistants.models.AiAssistant` — one row per
    stored assistant. Holds prompt, model, temperature, key ref,
    stop-keywords, retry attempts, fallback message, output
    sanitiser toggle + allowed-domains list (defence against
    insider prompt injection via ``instructions``), per-assistant
    budget-cap override, JSONB blobs for the interface + styling
    configs (Steps 12 + 13 populate).

  * :class:`~core.ai_assistants.models.AiAssistantKnowledge` — one
    row per uploaded / typed / URL-crawled knowledge source. Three
    source types (``file`` / ``text`` / ``url``); the same chunker
    pipeline runs on all three via Step 10's ingest task.

  * :class:`~core.ai_assistants.models.AiAssistantChunk` — one row
    per embedded chunk. Uses pgvector's ``VECTOR(1536)`` type;
    HNSW index enables cosine-distance top-K retrieval scoped
    per-org via RLS + a supporting composite b-tree on
    ``(org_id, status)``.

  * :class:`~core.ai_assistants.models.AiAssistantMessageMeta` —
    side-table on :class:`~core.conversations.models.Message` for
    AI-specific metadata (model, token counts, USD cost, cost
    outbox status, retrieved chunk ids for the audit trail). The
    reason for a side-table rather than columns on ``tbl_messages``:
    (a) message-metadata is only present on assistant replies, so
    a JOIN-in-when-needed keeps ``tbl_messages`` narrow for the
    inbox's hot path, and (b) the AI-Assistants module owns this
    schema and shouldn't hard-couple to the conversations table's
    layout.

  * :class:`~core.ai_assistants.models.AiAssistantInstructionAudit`
    — one row per operator change to ``instructions`` / ``model`` /
    ``temperature``. Written from Step 8's tab-save flow so an
    insider inserting a URL-exfiltration prompt shows up in the
    audit trail with a diff.

AI-widget conversations reuse ``tbl_conversations`` (with the new
enum value ``ai_widget`` on the ``conversation_channel`` ENUM) +
``tbl_messages`` for the transport; the message-meta side-table
above holds the AI-specific per-message data.

The BYOK provider key each assistant uses lives in
:mod:`core.integrations.ai` (Step 1). Assistant CRUD is Step 6;
runtime + streaming is Step 9; ingest is Step 10.
"""
