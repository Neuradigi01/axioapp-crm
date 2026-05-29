"""Step 3.5.9 — `AudienceFilter` group_id mode + mixed-mode validation.

Pure schema-level tests that lock down the contract the campaign
audience builder UI (Step 3.5.9 frontend) depends on. The full
resolve_audience integration (group_id → resolve_group_contacts
delegation) is covered by manual smoke + the downstream
dispatch_chunk tests; here we just guard the validator.
"""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.app.core.campaigns.schemas import AudienceFilter


class TestAudienceFilterModes:
    def test_empty_filter_is_valid(self):
        """`{}` = 'everyone in the org' — the default per Step 3.5.9
        UI recommendation."""
        af = AudienceFilter()
        assert af.q is None
        assert af.source is None
        assert af.tag is None
        assert af.group_id is None

    def test_filter_only(self):
        af = AudienceFilter(q="ash", source="walk-in", tag="vip")
        assert af.q == "ash"
        assert af.source == "walk-in"
        assert af.tag == "vip"
        assert af.group_id is None

    def test_group_id_only(self):
        gid = uuid.uuid4()
        af = AudienceFilter(group_id=gid)
        assert af.group_id == gid
        assert af.q is None
        assert af.source is None
        assert af.tag is None

    def test_filter_plus_group_id_rejected(self):
        """Mixing a filter field with `group_id` is the one combination
        the builder UI's radio toggle can't produce — but a direct API
        call could, so the schema rejects it to keep dispatch's
        resolution path unambiguous."""
        with pytest.raises(ValidationError, match="not both"):
            AudienceFilter(tag="vip", group_id=uuid.uuid4())

    def test_q_plus_group_id_rejected(self):
        with pytest.raises(ValidationError, match="not both"):
            AudienceFilter(q="ash", group_id=uuid.uuid4())

    def test_source_plus_group_id_rejected(self):
        with pytest.raises(ValidationError, match="not both"):
            AudienceFilter(source="walk-in", group_id=uuid.uuid4())

    def test_empty_string_filter_fields_not_treated_as_set(self):
        """Defensive: a UI that ships empty-string filter values
        alongside a group_id shouldn't trigger the mixed-mode error.
        Empty strings are falsy, so the validator's `bool(...)` check
        treats them as 'not set'."""
        # Per validator: `has_filter = bool(self.q or ...)` — "" is False.
        af = AudienceFilter(q="", source="", tag="", group_id=uuid.uuid4())
        assert af.group_id is not None
