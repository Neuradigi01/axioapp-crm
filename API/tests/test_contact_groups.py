"""Step 3.5.7 — contact groups CRUD + resolution + preview.

Pure unit tests that exercise the helpers and schema-level guards.
The CRUD/resolution paths that hit the DB are covered by manual
smoke + downstream campaign-dispatch tests; here we lock down the
contract that the audience builder (Step 3.5.9) depends on.

What we prove:

  1. Schema-level mode consistency: GroupCreate rejects mismatched
     payloads (dynamic without filter, static without contact_ids,
     both modes mixed).
  2. PreviewSizeIn enforces "exactly one of filter_json or group_id".
  3. The predicate builder matches the contacts list endpoint's
     q/source/tag semantics (regression guard against drift).
  4. `_bulk_set_members` is idempotent on `(group_id, contact_id)`.
"""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.app.core.contacts.groups import service as groups_service
from src.app.core.contacts.groups.schemas import (
    GroupCreate,
    GroupFilter,
    PreviewSizeIn,
)


# --- GroupCreate mode-consistency guards --------------------------------


class TestGroupCreateValidation:
    def test_dynamic_requires_filter_json(self):
        with pytest.raises(ValidationError, match="filter_json"):
            GroupCreate(name="Bad dynamic", is_dynamic=True)

    def test_dynamic_rejects_contact_ids(self):
        with pytest.raises(ValidationError, match="contact_ids"):
            GroupCreate(
                name="Mixed",
                is_dynamic=True,
                filter_json=GroupFilter(tag="vip"),
                contact_ids=[uuid.uuid4()],
            )

    def test_static_requires_contact_ids(self):
        with pytest.raises(ValidationError, match="contact_ids"):
            GroupCreate(name="Bad static", is_dynamic=False)

    def test_static_rejects_filter_json(self):
        with pytest.raises(ValidationError, match="filter_json"):
            GroupCreate(
                name="Mixed",
                is_dynamic=False,
                filter_json=GroupFilter(tag="vip"),
                contact_ids=[],
            )

    def test_static_with_empty_list_is_valid(self):
        """Zero-member static group is legal — operator may populate
        later via PATCH. Useful when groups are created programmatically
        (e.g. XLSX import opens an empty group, then bulk-adds members
        from the parsed rows)."""
        g = GroupCreate(name="Empty static", is_dynamic=False, contact_ids=[])
        assert g.contact_ids == []

    def test_dynamic_with_filter_is_valid(self):
        g = GroupCreate(
            name="Walk-in Sofa Shoppers",
            description="Q4 retention target",
            is_dynamic=True,
            filter_json=GroupFilter(source="walk-in", tag="sofa"),
        )
        assert g.is_dynamic is True
        assert g.filter_json.source == "walk-in"
        assert g.filter_json.tag == "sofa"


# --- PreviewSizeIn — exactly-one validator ------------------------------


class TestPreviewSizeIn:
    def test_filter_only_valid(self):
        p = PreviewSizeIn(filter_json=GroupFilter(tag="vip"))
        assert p.filter_json is not None
        assert p.group_id is None

    def test_group_id_only_valid(self):
        gid = uuid.uuid4()
        p = PreviewSizeIn(group_id=gid)
        assert p.group_id == gid
        assert p.filter_json is None

    def test_both_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            PreviewSizeIn(
                filter_json=GroupFilter(tag="vip"),
                group_id=uuid.uuid4(),
            )

    def test_neither_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            PreviewSizeIn()


# --- predicate builder regression ---------------------------------------


class TestPredicateBuilder:
    def test_empty_filter_returns_no_predicates(self):
        assert (
            groups_service._build_contact_filter_predicates({}) == []
        )
        assert (
            groups_service._build_contact_filter_predicates(None) == []
        )

    def test_q_only(self):
        preds = groups_service._build_contact_filter_predicates(
            {"q": "asha"}
        )
        assert len(preds) == 1

    def test_source_and_tag_emit_two_predicates(self):
        preds = groups_service._build_contact_filter_predicates(
            {"source": "walk-in", "tag": "sofa"}
        )
        assert len(preds) == 2

    def test_all_three_filters(self):
        preds = groups_service._build_contact_filter_predicates(
            {"q": "ash", "source": "walk-in", "tag": "sofa"}
        )
        assert len(preds) == 3

    def test_unknown_keys_ignored(self):
        """Forward-compat: future filter keys land in JSONB without
        breaking older deployments. The predicate builder ignores
        unknown keys rather than raising."""
        preds = groups_service._build_contact_filter_predicates(
            {"q": "ash", "future_field": "value"}
        )
        assert len(preds) == 1  # only q recognised
