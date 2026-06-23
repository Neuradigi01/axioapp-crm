"""whatsapp-platform-upgrade Step 18 — assignment engine tests.

Pure-Python boundary tests around schema validation +
_coerce_uuid_list helper. Strategy distribution (round-robin
rotation, load-balanced lowest-count pick) is covered by
integration tests against a live DB once the migration lands —
the picker functions need a real session for ``SELECT FOR UPDATE``.

Cases:
  1. RoundRobin schema rejects empty eligible_user_ids.
  2. RoundRobin schema rejects non-UUID entries.
  3. LoadBalanced schema rejects negative cap_per_user.
  4. LoadBalanced schema accepts null cap_per_user.
  5. TagBased schema rejects empty mapping.
  6. TagBased schema rejects non-UUID keys / values.
  7. TeamBased schema requires team_id.
  8. _coerce_uuid_list filters out non-UUIDs.
"""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.app.core.integrations.whatsapp.assignment_engine import (
    _coerce_uuid_list,
)
from src.app.core.integrations.whatsapp.schemas import (
    AssignmentRuleUpsert,
)


def _uid() -> str:
    return str(uuid.uuid4())


class TestRoundRobinSchema:
    def test_empty_users_rejected(self):
        with pytest.raises(ValidationError):
            AssignmentRuleUpsert(
                name="rr",
                strategy="round_robin",
                config={"eligible_user_ids": []},
            )

    def test_non_uuid_rejected(self):
        with pytest.raises(ValidationError):
            AssignmentRuleUpsert(
                name="rr",
                strategy="round_robin",
                config={"eligible_user_ids": ["not-a-uuid"]},
            )

    def test_valid_passes(self):
        rule = AssignmentRuleUpsert(
            name="rr",
            strategy="round_robin",
            config={"eligible_user_ids": [_uid(), _uid()]},
        )
        assert rule.strategy == "round_robin"
        assert len(rule.config["eligible_user_ids"]) == 2


class TestLoadBalancedSchema:
    def test_negative_cap_rejected(self):
        with pytest.raises(ValidationError):
            AssignmentRuleUpsert(
                name="lb",
                strategy="load_balanced",
                config={
                    "eligible_user_ids": [_uid()],
                    "cap_per_user": -1,
                },
            )

    def test_zero_cap_rejected(self):
        with pytest.raises(ValidationError):
            AssignmentRuleUpsert(
                name="lb",
                strategy="load_balanced",
                config={
                    "eligible_user_ids": [_uid()],
                    "cap_per_user": 0,
                },
            )

    def test_null_cap_accepted(self):
        rule = AssignmentRuleUpsert(
            name="lb",
            strategy="load_balanced",
            config={
                "eligible_user_ids": [_uid()],
                "cap_per_user": None,
            },
        )
        assert rule.config["cap_per_user"] is None

    def test_positive_cap_accepted(self):
        rule = AssignmentRuleUpsert(
            name="lb",
            strategy="load_balanced",
            config={
                "eligible_user_ids": [_uid()],
                "cap_per_user": 25,
            },
        )
        assert rule.config["cap_per_user"] == 25


class TestTagBasedSchema:
    def test_empty_mapping_rejected(self):
        with pytest.raises(ValidationError):
            AssignmentRuleUpsert(
                name="tb",
                strategy="tag_based",
                config={"mapping": {}},
            )

    def test_non_uuid_keys_rejected(self):
        with pytest.raises(ValidationError):
            AssignmentRuleUpsert(
                name="tb",
                strategy="tag_based",
                config={"mapping": {"not-a-uuid": _uid()}},
            )

    def test_non_uuid_values_rejected(self):
        with pytest.raises(ValidationError):
            AssignmentRuleUpsert(
                name="tb",
                strategy="tag_based",
                config={"mapping": {_uid(): "not-a-uuid"}},
            )

    def test_valid_mapping_accepted(self):
        rule = AssignmentRuleUpsert(
            name="tb",
            strategy="tag_based",
            config={"mapping": {_uid(): _uid(), _uid(): _uid()}},
        )
        assert len(rule.config["mapping"]) == 2


class TestTeamBasedSchema:
    def test_team_id_required(self):
        with pytest.raises(ValidationError):
            AssignmentRuleUpsert(
                name="team",
                strategy="team_based",
                config={},
            )

    def test_non_uuid_team_rejected(self):
        with pytest.raises(ValidationError):
            AssignmentRuleUpsert(
                name="team",
                strategy="team_based",
                config={"team_id": "not-a-uuid"},
            )

    def test_valid_team(self):
        rule = AssignmentRuleUpsert(
            name="team",
            strategy="team_based",
            config={"team_id": _uid()},
        )
        assert rule.strategy == "team_based"


class TestCoerceUuidList:
    def test_filters_non_uuids(self):
        good = str(uuid.uuid4())
        result = _coerce_uuid_list([good, "not-a-uuid", 12345])
        assert len(result) == 1
        assert str(result[0]) == good

    def test_empty_input(self):
        assert _coerce_uuid_list([]) == []

    def test_non_list_input(self):
        # Defensive — JSONB could surface a string by mistake.
        assert _coerce_uuid_list("not-a-list") == []  # type: ignore[arg-type]
