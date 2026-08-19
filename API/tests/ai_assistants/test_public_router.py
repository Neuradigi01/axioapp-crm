"""Focused tests for the AI-assistants public router
(``tasks/ai-assistants`` Step 14).

Covers the parts of the public surface that can be unit-tested
without a running Redis / Cloudflare / Celery stack:

  * ``PublicContext`` origin check (allow-list match + mismatch).
  * Assert helper rejects lead-form keys / missing resource_id.
  * Turnstile dev bypass token acceptance.
  * SSE registry register/cancel/deregister lifecycle.
  * ``resolve_embed_key`` accepts a grace-window key.

The full HTTP flow (bearer → SSE tokens) needs a running app +
Redis + a real embed key issued out-of-band; that's covered in
the smoke checklist rather than pytest.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from src.app.core.ai_assistants.public_context import _origin_matches
from src.app.core.ai_assistants.sse_registry import SseStreamRegistry
from src.app.core.embed import service as embed_service
from src.app.shared.turnstile import verify_turnstile


# --- Origin allow-list --------------------------------------------------


def test_origin_matches_exact() -> None:
    assert _origin_matches(
        "https://widget.example.com",
        ("https://widget.example.com",),
    )


def test_origin_matches_case_insensitive() -> None:
    assert _origin_matches(
        "HTTPS://Widget.EXAMPLE.com",
        ("https://widget.example.com",),
    )


def test_origin_matches_rejects_different_host() -> None:
    assert not _origin_matches(
        "https://evil.com",
        ("https://widget.example.com",),
    )


def test_origin_matches_rejects_different_scheme() -> None:
    assert not _origin_matches(
        "http://widget.example.com",
        ("https://widget.example.com",),
    )


def test_origin_matches_empty_list_rejects_all() -> None:
    # Router calls this only when allow-list is non-empty; the empty
    # case short-circuits at the caller, but we still document the
    # behaviour: an empty tuple never matches.
    assert not _origin_matches("https://x.com", ())


# --- assert_ai_assistant_key --------------------------------------------


def test_assert_rejects_none() -> None:
    with pytest.raises(HTTPException) as exc:
        embed_service.assert_ai_assistant_key(None)
    assert exc.value.status_code == 401
    assert exc.value.detail["reason"] == "invalid_key"


def test_assert_rejects_lead_form_key() -> None:
    resolved = embed_service.ResolvedEmbedKey(
        key_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        resource_type=embed_service.RESOURCE_TYPE_LEAD_FORM,
        resource_id=None,
        allowed_origins=(),
        rate_limit_per_hour=300,
        prefix="pk_live_XYZ",
    )
    with pytest.raises(HTTPException) as exc:
        embed_service.assert_ai_assistant_key(resolved)
    assert exc.value.status_code == 401
    assert exc.value.detail["reason"] == "invalid_key"


def test_assert_rejects_ai_assistant_with_null_resource_id() -> None:
    """Bad admin edit that leaves resource_id NULL on an ai_assistant
    row — the assert path treats it the same as an unknown key."""
    resolved = embed_service.ResolvedEmbedKey(
        key_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        resource_type=embed_service.RESOURCE_TYPE_AI_ASSISTANT,
        resource_id=None,
        allowed_origins=(),
        rate_limit_per_hour=300,
        prefix="pk_live_XYZ",
    )
    with pytest.raises(HTTPException) as exc:
        embed_service.assert_ai_assistant_key(resolved)
    assert exc.value.status_code == 401


def test_assert_accepts_valid_ai_assistant_key() -> None:
    resolved = embed_service.ResolvedEmbedKey(
        key_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        resource_type=embed_service.RESOURCE_TYPE_AI_ASSISTANT,
        resource_id=uuid.uuid4(),
        allowed_origins=("https://x.com",),
        rate_limit_per_hour=300,
        prefix="pk_live_XYZ",
    )
    out = embed_service.assert_ai_assistant_key(resolved)
    assert out is resolved


# --- Turnstile dev bypass -----------------------------------------------


@pytest.mark.asyncio
async def test_turnstile_dev_bypass_token_accepted() -> None:
    """When TURNSTILE_SECRET_KEY is empty, only Cloudflare's documented
    always-pass bypass tokens are accepted — no network round-trip."""
    # KEK is set globally in the smoke; TURNSTILE_SECRET_KEY defaults
    # to empty in the test env so the dev path fires.
    import config

    prior = config.TURNSTILE_SECRET_KEY
    config.TURNSTILE_SECRET_KEY = ""
    try:
        assert await verify_turnstile("1x0000000000000000000000000000000AA") is True
        assert await verify_turnstile("2x0000000000000000000000000000000AA") is True
        assert await verify_turnstile("not-a-bypass") is False
        assert await verify_turnstile(None) is False
        assert await verify_turnstile("") is False
    finally:
        config.TURNSTILE_SECRET_KEY = prior


# --- SSE stream registry ------------------------------------------------


def test_registry_register_and_deregister() -> None:
    reg = SseStreamRegistry()
    kid = uuid.uuid4()
    reg.register(embed_key_id=kid, session_token="t1")
    assert reg.active_count() == 1
    reg.deregister(embed_key_id=kid, session_token="t1")
    assert reg.active_count() == 0


def test_registry_cancel_by_embed_key_flips_only_matching() -> None:
    reg = SseStreamRegistry()
    key_a = uuid.uuid4()
    key_b = uuid.uuid4()
    reg.register(embed_key_id=key_a, session_token="s1")
    reg.register(embed_key_id=key_a, session_token="s2")
    reg.register(embed_key_id=key_b, session_token="s3")

    cancelled = reg.cancel_by_embed_key(key_a)
    assert cancelled == 2
    assert reg.is_cancelled(embed_key_id=key_a, session_token="s1") is True
    assert reg.is_cancelled(embed_key_id=key_a, session_token="s2") is True
    assert reg.is_cancelled(embed_key_id=key_b, session_token="s3") is False


def test_registry_cancel_returns_zero_when_no_matching() -> None:
    reg = SseStreamRegistry()
    reg.register(embed_key_id=uuid.uuid4(), session_token="s1")
    assert reg.cancel_by_embed_key(uuid.uuid4()) == 0


def test_registry_is_cancelled_returns_false_for_missing() -> None:
    reg = SseStreamRegistry()
    assert reg.is_cancelled(embed_key_id=uuid.uuid4(), session_token="ghost") is False


# --- Rotate cap ---------------------------------------------------------


@pytest.mark.asyncio
async def test_rotate_rejects_out_of_range_grace_days() -> None:
    """Server rejects grace_days>7 (or <0) even if the operator UI
    somehow lets it through. Doesn't need a DB session — the guard
    fires before any DAL call."""
    from src.app.core.embed import service as _service

    for bad in (-1, 8, 30, 365):
        with pytest.raises(HTTPException) as exc:
            await _service.rotate(
                None,  # type: ignore[arg-type] — never reaches session use
                org_id=uuid.uuid4(),
                actor_id=uuid.uuid4(),
                key_id=uuid.uuid4(),
                grace_days=bad,
            )
        assert exc.value.status_code == 400
        assert exc.value.detail["reason"] == "grace_days_out_of_range"


# --- Issue rejects invalid resource_type --------------------------------


@pytest.mark.asyncio
async def test_issue_rejects_invalid_resource_type() -> None:
    with pytest.raises(HTTPException) as exc:
        await embed_service.issue(
            None,  # type: ignore[arg-type]
            org_id=uuid.uuid4(),
            actor_id=uuid.uuid4(),
            resource_type="widget_bomb",
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["reason"] == "invalid_resource_type"


@pytest.mark.asyncio
async def test_issue_rejects_ai_assistant_without_resource_id() -> None:
    with pytest.raises(HTTPException) as exc:
        await embed_service.issue(
            None,  # type: ignore[arg-type]
            org_id=uuid.uuid4(),
            actor_id=uuid.uuid4(),
            resource_type=embed_service.RESOURCE_TYPE_AI_ASSISTANT,
            resource_id=None,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["reason"] == "resource_id_required_for_ai_assistant"


# --- Grace-window semantics on the model --------------------------------


def test_embed_key_is_live_within_grace_window() -> None:
    from src.app.core.embed.models import EmbedKey

    now = datetime.now(UTC)
    row = EmbedKey(
        prefix="pk_live_XYZ",
        hash="dummy",
        created_by=uuid.uuid4(),
        revoked_at=now - timedelta(hours=1),
        grace_expires_at=now + timedelta(hours=6),
    )
    assert row.is_live(now=now) is True
    assert row.is_live(now=now + timedelta(hours=7)) is False


def test_embed_key_is_live_when_never_revoked() -> None:
    from src.app.core.embed.models import EmbedKey

    now = datetime.now(UTC)
    row = EmbedKey(
        prefix="pk_live_XYZ",
        hash="dummy",
        created_by=uuid.uuid4(),
    )
    assert row.is_live(now=now) is True


def test_embed_key_hard_revoked_no_grace() -> None:
    from src.app.core.embed.models import EmbedKey

    now = datetime.now(UTC)
    row = EmbedKey(
        prefix="pk_live_XYZ",
        hash="dummy",
        created_by=uuid.uuid4(),
        revoked_at=now - timedelta(minutes=1),
        grace_expires_at=None,
    )
    assert row.is_live(now=now) is False
