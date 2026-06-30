"""Mutual-check between ``feature_keys.py`` and ``plans.yaml``.

Hard-coded strings on the call site (``@requires_feature("automaton.workflows")``)
are silently wrong — a typo just means the feature is never granted. The
constants module makes typos compile-time errors instead, but only if it
stays in lock-step with the YAML.

These two tests enforce that lock-step in both directions:

  - Every ``FEATURE_*`` constant in ``feature_keys.py`` resolves to a
    key that ``plans.yaml`` actually declares (via ``KNOWN_FEATURE_KEYS``).
    Catches stale constants left behind after a YAML rename.
  - Every key in ``KNOWN_FEATURE_KEYS`` has a matching ``FEATURE_*``
    constant. Catches new YAML keys the constants module forgot to add.
"""

from __future__ import annotations

from src.app.core.subscriptions import feature_keys
from src.app.core.subscriptions.plans import KNOWN_FEATURE_KEYS


def _collect_feature_constants() -> dict[str, str]:
    """All ``FEATURE_*`` attributes on the module → their string values."""
    return {
        name: value
        for name, value in vars(feature_keys).items()
        if name.startswith("FEATURE_") and isinstance(value, str)
    }


def test_every_constant_matches_a_yaml_key():
    """No stale constant lingers after a YAML rename or deletion."""
    constants = _collect_feature_constants()
    assert constants, "feature_keys.py exposed no FEATURE_* constants — empty module?"

    for name, value in constants.items():
        assert value in KNOWN_FEATURE_KEYS, (
            f"{name}={value!r} does not appear in plans.yaml's KNOWN_FEATURE_KEYS. "
            "Either add the YAML key or remove the constant."
        )


def test_every_yaml_key_has_a_constant():
    """No YAML feature key is missing a typed constant for call sites to import."""
    constants_by_value = {value: name for name, value in _collect_feature_constants().items()}

    missing: list[str] = []
    for key in KNOWN_FEATURE_KEYS:
        if key not in constants_by_value:
            expected_name = "FEATURE_" + key.upper().replace(".", "_")
            missing.append(f"  - {expected_name} = {key!r}")

    assert not missing, (
        "plans.yaml has feature keys with no matching FEATURE_* constant in "
        "feature_keys.py. Add:\n" + "\n".join(missing)
    )


def test_constants_use_screaming_snake_case_naming():
    """Defensive: catch a constant accidentally introduced in the wrong shape."""
    for name in _collect_feature_constants():
        assert name == name.upper(), f"{name!r} is not SCREAMING_SNAKE_CASE"
        assert " " not in name and "-" not in name, f"{name!r} must use underscores only"
