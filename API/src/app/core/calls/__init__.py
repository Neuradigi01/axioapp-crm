"""Call-center module — calls + transcripts + outcomes config.

Re-exports the service entry points so other modules can call into
the call-center without importing FastAPI/Pydantic types.
"""

from src.app.core.calls.service import (
    analytics,
    create_call,
    create_outcome,
    delete_call,
    delete_outcome,
    get_call,
    get_transcript,
    list_calls,
    list_outcomes,
    update_call,
    update_outcome,
    upsert_transcript,
)

__all__ = [
    "analytics",
    "create_call",
    "create_outcome",
    "delete_call",
    "delete_outcome",
    "get_call",
    "get_transcript",
    "list_calls",
    "list_outcomes",
    "update_call",
    "update_outcome",
    "upsert_transcript",
]
