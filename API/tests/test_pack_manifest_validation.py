"""Schema validation for `pack.yaml`.

Every rule the manifest enforces lives in `PackManifest` /
`PipelineManifest`. The tests below assert each one:

- key shape: must match `[a-z][a-z0-9_]*`
- duplicate keys within a section are rejected
- pipeline must declare exactly one is_won stage
- a stage can't be both is_won and is_lost
- unknown top-level fields are rejected (`extra='forbid'`)
"""
from __future__ import annotations

import pytest

from src.app.core.packs.loader import PackLoadError, load_pack_dict


def _minimal() -> dict:
    return {
        "template_id": "tinypack",
        "version": "0.1.0",
        "display_name": "Tiny",
        "pipelines": [
            {
                "key": "leads",
                "name": "Leads",
                "stages": [
                    {"key": "new", "name": "New", "display_order": 0},
                    {
                        "key": "won",
                        "name": "Won",
                        "display_order": 1,
                        "is_won": True,
                    },
                ],
            }
        ],
    }


def test_minimal_manifest_parses():
    m = load_pack_dict(_minimal())
    assert m.template_id == "tinypack"
    assert m.version == "0.1.0"
    assert len(m.pipelines) == 1
    assert len(m.pipelines[0].stages) == 2


def test_invalid_template_id_shape_rejected():
    data = _minimal()
    data["template_id"] = "Tiny-Pack"  # capital + dash, rejected by _validate_key
    with pytest.raises(PackLoadError):
        load_pack_dict(data)


def test_duplicate_pipeline_keys_rejected():
    data = _minimal()
    data["pipelines"].append(data["pipelines"][0])  # same key
    with pytest.raises(PackLoadError):
        load_pack_dict(data)


def test_pipeline_without_is_won_rejected():
    data = _minimal()
    data["pipelines"][0]["stages"] = [
        {"key": "new", "name": "New", "display_order": 0}
    ]
    with pytest.raises(PackLoadError):
        load_pack_dict(data)


def test_pipeline_with_two_is_won_rejected():
    data = _minimal()
    data["pipelines"][0]["stages"][0]["is_won"] = True
    with pytest.raises(PackLoadError):
        load_pack_dict(data)


def test_stage_cannot_be_both_won_and_lost():
    data = _minimal()
    data["pipelines"][0]["stages"][1]["is_lost"] = True
    with pytest.raises(PackLoadError):
        load_pack_dict(data)


def test_duplicate_custom_field_rejected():
    data = _minimal()
    data["custom_fields"] = [
        {
            "entity_type": "lead",
            "field_key": "budget",
            "field_label": "Budget",
            "field_type": "currency",
            "display_order": 0,
        },
        {
            "entity_type": "lead",
            "field_key": "budget",
            "field_label": "Budget v2",
            "field_type": "currency",
            "display_order": 1,
        },
    ]
    with pytest.raises(PackLoadError):
        load_pack_dict(data)


def test_unknown_top_level_field_rejected():
    data = _minimal()
    data["surprise"] = True
    with pytest.raises(PackLoadError):
        load_pack_dict(data)
