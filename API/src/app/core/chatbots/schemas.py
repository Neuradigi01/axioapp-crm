"""Pydantic v2 schemas for the chatbots module.

Two concept groups:

  * **Bot CRUD** — :class:`ChatbotCreate`, :class:`ChatbotUpdate`,
    :class:`ChatbotRead`. ``ChatbotUpdate`` carries an
    ``expected_version`` field for optimistic locking (Case #27).
  * **Graph shape** — :class:`ChatbotGraph` with
    :class:`ChatbotNode` + :class:`ChatbotEdge`. The Pydantic layer
    enforces structural rules (unique ids, edge endpoints resolve);
    :mod:`core.chatbots.graph` layers the semantic rules
    (DAG, node-type parity, connect-flow chain depth).

Per-node config schemas are intentionally deferred to each node's
step (Steps 7-10) — the top-level ``config: dict`` slot here keeps
the shape flexible while every handler owns its own strict schema
in its file. Trade-off: Pydantic can't 422 on a bad
button-count-of-5 at save-time until Step 7 registers the button-
node schema. That's fine — Step 2's job is to lock the frame, not
the paint.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- Trigger config -------------------------------------------------------


class TriggerConfig(BaseModel):
    """The one trigger per bot (Decision §3).

    Stored on ``tbl_chatbots.trigger_config``. The Step-5 matcher
    reads this to decide whether an inbound message fires this bot.
    """

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(default="any", pattern=r"^(any|whatsapp|email)$")
    mode: str = Field(default="any", pattern=r"^(any|keyword|regex)$")
    keywords: list[str] = Field(default_factory=list, max_length=200)
    regex_pattern: str | None = Field(default=None, max_length=500)
    case_sensitive: bool = False
    first_message_only: bool = False

    @field_validator("keywords")
    @classmethod
    def _keywords_non_empty_strings(cls, v: list[str]) -> list[str]:
        cleaned = [k.strip() for k in v if isinstance(k, str) and k.strip()]
        for k in cleaned:
            if len(k) > 100:
                raise ValueError(f"keyword too long (>100 chars): {k[:30]!r}…")
        return cleaned

    @model_validator(mode="after")
    def _mode_matches_config(self) -> TriggerConfig:
        if self.mode == "keyword" and not self.keywords:
            raise ValueError("mode='keyword' requires at least one keyword")
        if self.mode == "regex" and not self.regex_pattern:
            raise ValueError("mode='regex' requires regex_pattern")
        return self


# --- Graph shape ----------------------------------------------------------


class NodePosition(BaseModel):
    """Canvas coordinates. Round-tripped for the Pabbly-style builder
    so nodes stay put across save/load. Engine ignores position."""

    model_config = ConfigDict(extra="forbid")

    x: float = 0.0
    y: float = 0.0


class ChatbotNode(BaseModel):
    """One node in the bot graph. ``type`` is the registry key (e.g.
    ``text_button``, ``ask_question``, ``connect_flow``); per-node
    schemas ship with each node handler (Steps 7-10)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    type: str = Field(..., min_length=1, max_length=64)
    position: NodePosition = Field(default_factory=NodePosition)
    config: dict[str, Any] = Field(default_factory=dict)


class ChatbotEdge(BaseModel):
    """Directed edge. ``label`` carries the branch discriminator (e.g.
    ``button_1`` / ``answered`` / ``invalid`` / ``timeout``)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    source: str = Field(..., min_length=1, max_length=64)
    target: str = Field(..., min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=64)


class ChatbotGraph(BaseModel):
    """The ``{nodes, edges}`` payload stored on ``tbl_chatbots.graph``.

    Structural enforcement at the Pydantic layer:

      * No duplicate node ids.
      * No duplicate edge ids.
      * Every edge references node ids present in the graph.

    Semantic rules (DAG, node-type parity, chain depth) live in
    :func:`core.chatbots.graph.validate_graph`.
    """

    model_config = ConfigDict(extra="forbid")

    nodes: list[ChatbotNode] = Field(default_factory=list)
    edges: list[ChatbotEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _structural_checks(self) -> ChatbotGraph:
        node_ids = [n.id for n in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("duplicate node ids in graph")
        edge_ids = [e.id for e in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("duplicate edge ids in graph")
        node_id_set = set(node_ids)
        for e in self.edges:
            if e.source not in node_id_set:
                raise ValueError(f"edge '{e.id}' source '{e.source}' not in nodes")
            if e.target not in node_id_set:
                raise ValueError(f"edge '{e.id}' target '{e.target}' not in nodes")
        return self


# --- Bot CRUD -------------------------------------------------------------


class ChatbotCreate(BaseModel):
    """Payload for ``POST /api/v1/chatbots``. Trigger + graph default
    to empty so the operator can create a shell and edit it."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category: str = Field(default="Custom", max_length=64)
    folder_id: uuid.UUID | None = None
    priority: int = Field(default=100, ge=0, le=1000)
    trigger_config: TriggerConfig = Field(default_factory=TriggerConfig)
    graph: ChatbotGraph = Field(default_factory=ChatbotGraph)


class ChatbotUpdate(BaseModel):
    """Payload for ``PATCH /api/v1/chatbots/{id}``. ``expected_version``
    powers optimistic locking (Case #27); a mismatch returns 409.

    Any field left ``None`` is not touched; explicit updates carry
    the new value. ``graph`` and ``trigger_config`` are full
    replacements (not partial merges) — the canvas always sends the
    complete authoritative shape.
    """

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(..., ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=64)
    folder_id: uuid.UUID | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    trigger_config: TriggerConfig | None = None
    graph: ChatbotGraph | None = None
    change_note: str | None = Field(default=None, max_length=500)


class ChatbotRead(BaseModel):
    """Full bot payload returned by GET and PATCH endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    category: str
    folder_id: uuid.UUID | None
    status: str
    priority: int
    trigger_config: dict[str, Any]
    graph: dict[str, Any]
    version_number: int
    created_by_user_id: uuid.UUID | None
    updated_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ChatbotListItem(BaseModel):
    """Compact row for the list page — no full graph payload."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    category: str
    folder_id: uuid.UUID | None
    status: str
    priority: int
    trigger_config: dict[str, Any]
    version_number: int
    updated_at: datetime


class ChatbotVersionRead(BaseModel):
    """One row of version history."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chatbot_id: uuid.UUID
    version_number: int
    graph: dict[str, Any]
    trigger_config: dict[str, Any]
    change_note: str | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime


# --- Test-fire (Step 6) --------------------------------------------------


class TestFireRequest(BaseModel):
    """POST body for ``/chatbots/{id}/test-fire`` (Case #22 / Decision §17).

    The endpoint always runs dry — the ``dry_run`` flag is not
    operator-settable; sends are transcript-only, save-to writes
    land in a per-run scratch, and the run row is auto-deleted after
    24h via :func:`core.chatbots.tasks.sweep_test_runs`.
    """

    model_config = ConfigDict(extra="forbid")

    simulated_inbound_text: str = Field(..., min_length=0, max_length=4096)
    simulated_channel: str = Field(default="whatsapp", pattern=r"^(whatsapp|email)$")
    simulated_contact_id: uuid.UUID | None = None
    simulated_conversation_id: uuid.UUID | None = None
    simulated_is_first_message: bool = False


class TestFireStepEntry(BaseModel):
    """One line in the test-fire transcript."""

    model_config = ConfigDict(from_attributes=True)

    node_id: str
    node_type: str
    status: str
    output_edge_label: str | None
    skip_reason: str | None
    error: str | None
    output: dict[str, Any]


class TestFireResponse(BaseModel):
    """Test-fire result. Callers render ``steps`` as a transcript
    and ``final_status`` in the header (``completed`` / ``canceled``
    / ``errored`` / ``parked``)."""

    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    final_status: str
    canceled_reason: str | None
    error: str | None
    steps: list[TestFireStepEntry]


# --- Export / Import (Step 15) -------------------------------------------


CHATBOT_EXPORT_VERSION = 1


class ChatbotExportBotBody(BaseModel):
    """Inner ``bot`` payload of the export envelope. Deliberately
    plain — no org UUIDs, user emails, or HMAC keys are ever exported.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None
    category: str
    priority: int
    trigger_config: dict[str, Any]
    graph: dict[str, Any]
    referenced_custom_fields: list[dict[str, Any]]
    referenced_templates: list[dict[str, Any]]


class ChatbotExportEnvelope(BaseModel):
    """Portable bot export — round-trips through the import endpoint
    to reconstruct the bot in a different org with new IDs."""

    model_config = ConfigDict(extra="forbid")

    chatbot_export_version: int = Field(default=CHATBOT_EXPORT_VERSION)
    exported_at: datetime
    source_org_name: str
    bot: ChatbotExportBotBody


class ChatbotImportRequest(BaseModel):
    """POST body for ``/chatbots/import``. Accepts the same shape the
    export endpoint produces."""

    model_config = ConfigDict(extra="forbid")

    envelope: ChatbotExportEnvelope
    # Operator can override the imported bot's name to disambiguate
    # from an existing bot with the same name in this org.
    name_override: str | None = Field(default=None, min_length=1, max_length=200)


class ChatbotImportConflict(BaseModel):
    """One conflict item surfaced to the operator during import
    preview / commit."""

    model_config = ConfigDict(extra="forbid")

    kind: str  # "missing_custom_field" | "missing_template" | "name_collision"
    detail: str


class ChatbotImportResult(BaseModel):
    """Import outcome — includes any conflicts the operator should
    know about (missing custom fields, missing templates)."""

    model_config = ConfigDict(extra="forbid")

    created_bot_id: uuid.UUID
    conflicts: list[ChatbotImportConflict]
