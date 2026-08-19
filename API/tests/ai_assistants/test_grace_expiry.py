"""Embed key grace expiry task tests
(``tasks/ai-assistants`` Step 17).

Tests the grace-period expiry logic for revoked embed keys.
"""

from __future__ import annotations

import pytest

# Side-effect imports for FK resolution
import src.app.core.embed.models  # noqa: F401,E402


def test_embed_key_has_grace_expires_at():
    """EmbedKey model has grace_expires_at timestamp column for the
    rotate-with-grace feature (Step 17)."""
    from src.app.core.embed.models import EmbedKey

    assert hasattr(EmbedKey, 'grace_expires_at')
    grace_col = EmbedKey.__table__.c.grace_expires_at
    assert grace_col.nullable is True  # NULL = no grace period


def test_embed_key_has_revoked_at():
    """EmbedKey model has revoked_at timestamp for soft-revoke tracking."""
    from src.app.core.embed.models import EmbedKey

    assert hasattr(EmbedKey, 'revoked_at')
    revoked_col = EmbedKey.__table__.c.revoked_at
    assert revoked_col.nullable is True  # NULL = not revoked


@pytest.mark.asyncio
async def test_expire_embed_key_grace_task_registered():
    """expire_embed_key_grace is registered in Celery beat schedule."""
    from src.celery.celery_config import beat_schedule

    assert "ai-expire-embed-key-grace" in beat_schedule
    task_config = beat_schedule["ai-expire-embed-key-grace"]
    assert "src.app.core.ai_assistants.tasks.expire_embed_key_grace" in task_config["task"]
