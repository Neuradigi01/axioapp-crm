"""whatsapp-platform-upgrade Step 14 — conversation tags tests.

Pure-Python boundary tests around the Pydantic schemas + palette
validation. Integration-style assignment + cascade-delete behavior
is covered by the broader conversation-CRUD test suite once the
migration lands.

Cases:
  1. `TagCreate` rejects empty / over-length name.
  2. `TagCreate` rejects unknown color.
  3. `TagCreate` strips whitespace from name.
  4. Default color is `zinc`.
  5. `TagUpdate` accepts no fields (no-op patch).
  6. `TagUpdate` rejects unknown color.
  7. `AssignTagRequest` requires a UUID.
  8. Color palette set matches the documented size (12).
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.app.core.conversations.schemas import (
    _TAG_COLORS,
    AssignTagRequest,
    TagCreate,
    TagUpdate,
)


class TestTagCreate:
    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            TagCreate(name="")

    def test_whitespace_only_name_rejected(self):
        # str_strip_whitespace=True trims first → "" → fails min_length.
        with pytest.raises(ValidationError):
            TagCreate(name="   ")

    def test_over_length_name_rejected(self):
        with pytest.raises(ValidationError):
            TagCreate(name="x" * 65)

    def test_unknown_color_rejected(self):
        with pytest.raises(ValidationError):
            TagCreate(name="high-value", color="neon-pink")

    def test_default_color_is_zinc(self):
        tag = TagCreate(name="urgent")
        assert tag.color == "zinc"

    def test_name_is_trimmed(self):
        tag = TagCreate(name="  high-value  ", color="rose")
        assert tag.name == "high-value"

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            TagCreate(
                name="urgent",
                color="rose",
                org_id="foo",  # type: ignore[call-arg]
            )

    def test_every_palette_color_accepted(self):
        # Defensive: looping through the documented palette catches a
        # typo where a color in the set isn't actually wired.
        for color in _TAG_COLORS:
            tag = TagCreate(name="test", color=color)
            assert tag.color == color


class TestTagUpdate:
    def test_empty_patch_validates(self):
        # `PATCH` with no fields is a documented no-op at the service
        # layer; the schema must accept it.
        patch = TagUpdate()
        assert patch.model_dump(exclude_unset=True) == {}

    def test_unknown_color_rejected(self):
        with pytest.raises(ValidationError):
            TagUpdate(color="neon-pink")

    def test_rename_only(self):
        patch = TagUpdate(name="vip")
        assert patch.name == "vip"
        assert patch.color is None

    def test_recolor_only(self):
        patch = TagUpdate(color="rose")
        assert patch.color == "rose"
        assert patch.name is None


class TestAssignTagRequest:
    def test_uuid_string_parses(self):
        u = str(uuid.uuid4())
        req = AssignTagRequest(tag_id=u)
        assert isinstance(req.tag_id, uuid.UUID)

    def test_non_uuid_rejected(self):
        with pytest.raises(ValidationError):
            AssignTagRequest(tag_id="not-a-uuid")

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            AssignTagRequest(
                tag_id=str(uuid.uuid4()),
                conversation_id="x",  # type: ignore[call-arg]
            )


class TestPaletteInvariant:
    def test_palette_size_locked(self):
        # If you add a color to `_TAG_COLORS`, update this expectation
        # AND the Tailwind class map on the frontend
        # (`TAG_COLOR_CLASSES` in `conversations-api.service.ts`).
        # Keeping the two in lockstep is the whole point of a fixed
        # palette — surfaces should never disagree about what colors
        # exist.
        assert len(_TAG_COLORS) == 12
