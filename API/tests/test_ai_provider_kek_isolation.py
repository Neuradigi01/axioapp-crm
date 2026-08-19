"""Startup pin-test — ensure ``AI_PROVIDER_KEY_KEK`` is isolated from
every other secret in ``config.py``.

The BYOK provider-key store (``tasks/ai-assistants`` Step 1) encrypts
each org's OpenAI API key with a dedicated KEK. Sharing that KEK with
another secret means one env-var leak decrypts every secret in the
app — the same failure mode we're avoiding by using AES-GCM with AAD
in the first place.

This test is deliberately loud: if it fails in CI, the operator
mis-configured the deploy. Skipped when ``AI_PROVIDER_KEY_KEK`` is
unset, so devs can boot the app without a KEK and only pay the cost
once an org actually stores an API key.
"""

from __future__ import annotations

import base64

import pytest

import config as app_config


def _decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def test_kek_length_when_set() -> None:
    """When set, KEK must decode to exactly 32 bytes (AES-256 requires it)."""
    if not app_config.AI_PROVIDER_KEY_KEK:
        pytest.skip("AI_PROVIDER_KEY_KEK not set — pin-test skipped")
    raw = _decode(app_config.AI_PROVIDER_KEY_KEK)
    assert len(raw) == 32, (
        f"AI_PROVIDER_KEY_KEK must decode to 32 bytes, got {len(raw)}. "
        "Regenerate with: python -c 'import secrets, base64; "
        "print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'"
    )


@pytest.mark.parametrize(
    "other_var",
    [
        "INTEGRATIONS_ENCRYPTION_KEY",
        "FERNET_KEY",
        "JWT_SECRET_KEY",
        "PROPERTY_LINK_ENCRYPTION_KEY",
    ],
)
def test_kek_distinct_from_other_secret(other_var: str) -> None:
    """KEK must NOT equal any other secret. Sharing means one leak =
    every secret compromised."""
    if not app_config.AI_PROVIDER_KEY_KEK:
        pytest.skip("AI_PROVIDER_KEY_KEK not set — pin-test skipped")
    other_value = getattr(app_config, other_var, None) or ""
    if not other_value:
        pytest.skip(f"{other_var} not set — nothing to compare against")
    assert app_config.AI_PROVIDER_KEY_KEK != other_value, (
        f"AI_PROVIDER_KEY_KEK equals {other_var} — must be a distinct secret. "
        "Regenerate one with: python -c 'import secrets, base64; "
        "print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())' "
        "and update it in secrets.enc.env via `run secrets-edit`."
    )
