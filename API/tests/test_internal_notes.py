"""whatsapp-platform-upgrade Step 13 — internal notes tests.

Pure-Python boundary tests around the `NoteCreate` schema validation +
key invariants the notes service relies on. Integration-style tests
(actual DB writes + notification fanout) are covered by the broader
conversation-CRUD test suite once the migration lands.

Cases:
  1. Empty `text` rejected.
  2. Over-length `text` (> 4096 chars) rejected.
  3. > 5 mentions rejected (notification-fanout cap).
  4. Valid payload with 0 mentions accepted.
  5. Valid payload with 5 mentions accepted (at-cap).
  6. Mentions must be UUIDs — non-UUID strings rejected.
  7. `extra='forbid'` rejects unknown fields.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.app.core.conversations.schemas import NoteCreate


class TestNoteCreateValidation:
    def test_empty_text_rejected(self):
        with pytest.raises(ValidationError):
            NoteCreate(text="", mentions=[])

    def test_whitespace_only_text_rejected_after_strip(self):
        # `str_strip_whitespace=True` on the model trims first; an
        # all-whitespace value reduces to "" → fails min_length=1.
        with pytest.raises(ValidationError):
            NoteCreate(text="   ", mentions=[])

    def test_over_length_text_rejected(self):
        with pytest.raises(ValidationError):
            NoteCreate(text="x" * 4097, mentions=[])

    def test_six_mentions_rejected(self):
        ids = [str(uuid.uuid4()) for _ in range(6)]
        with pytest.raises(ValidationError):
            NoteCreate(text="ping team", mentions=ids)

    def test_five_mentions_accepted(self):
        ids = [str(uuid.uuid4()) for _ in range(5)]
        payload = NoteCreate(text="ping team", mentions=ids)
        assert len(payload.mentions) == 5

    def test_zero_mentions_accepted(self):
        payload = NoteCreate(text="just a note", mentions=[])
        assert payload.mentions == []

    def test_default_mentions_is_empty_list(self):
        payload = NoteCreate(text="just a note")
        assert payload.mentions == []

    def test_non_uuid_mention_rejected(self):
        with pytest.raises(ValidationError):
            NoteCreate(text="ping", mentions=["not-a-uuid"])

    def test_unknown_field_rejected(self):
        # `extra='forbid'` is the protection — passing a `channel`
        # field (or anything unknown) must reject so a misguided
        # frontend can't accidentally route a note through a channel
        # adapter.
        with pytest.raises(ValidationError):
            NoteCreate(
                text="ping",
                mentions=[],
                channel="whatsapp",  # type: ignore[call-arg]
            )

    def test_mention_uuid_string_parsed_to_uuid(self):
        u = str(uuid.uuid4())
        payload = NoteCreate(text="ping", mentions=[u])
        # Pydantic v2 parses the string into a UUID instance.
        assert isinstance(payload.mentions[0], uuid.UUID)
        assert str(payload.mentions[0]) == u
