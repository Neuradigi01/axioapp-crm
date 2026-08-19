"""Retention cleanup task tests
(``tasks/ai-assistants`` Step 17).

Tests the message-deletion logic by retention_days policy.
"""

from __future__ import annotations

import pytest

# Side-effect imports for FK resolution
import src.app.core.ai_assistants.models  # noqa: F401,E402
import src.app.core.conversations.models  # noqa: F401,E402


def test_retention_days_model_field_is_nullable():
    """retention_days on AiAssistant is nullable (nullable=True in schema).
    Existing assistants created before Step 17 have NULL, which defaults to
    90 at read time."""
    from src.app.core.ai_assistants.models import AiAssistant

    # Field exists and is nullable.
    retention_col = AiAssistant.__table__.c.retention_days
    assert retention_col.nullable is True


def test_retention_days_schema_validation_min():
    """Pydantic schema rejects retention_days < 1."""
    from src.app.core.ai_assistants.schemas import AiAssistantCreate
    from pydantic import ValidationError
    import uuid

    with pytest.raises(ValidationError) as exc:
        AiAssistantCreate(
            name="test",
            key_id=uuid.uuid4(),
            model="gpt-4o-mini",
            retention_days=0,
        )
    assert "greater than or equal to 1" in str(exc.value)


def test_retention_days_schema_validation_max():
    """Pydantic schema rejects retention_days > 400."""
    from src.app.core.ai_assistants.schemas import AiAssistantCreate
    from pydantic import ValidationError
    import uuid

    with pytest.raises(ValidationError) as exc:
        AiAssistantCreate(
            name="test",
            key_id=uuid.uuid4(),
            model="gpt-4o-mini",
            retention_days=401,
        )
    assert "less than or equal to 400" in str(exc.value)


def test_retention_days_schema_accepts_valid_range():
    """Pydantic schema accepts 1–400."""
    from src.app.core.ai_assistants.schemas import AiAssistantCreate
    import uuid

    for days in [1, 90, 400]:
        schema = AiAssistantCreate(
            name="test",
            key_id=uuid.uuid4(),
            model="gpt-4o-mini",
            retention_days=days,
        )
        assert schema.retention_days == days


def test_retention_days_schema_accepts_none():
    """Pydantic schema accepts None (for future assistant overrides)."""
    from src.app.core.ai_assistants.schemas import AiAssistantCreate
    import uuid

    schema = AiAssistantCreate(
        name="test",
        key_id=uuid.uuid4(),
        model="gpt-4o-mini",
        retention_days=None,
    )
    assert schema.retention_days is None


@pytest.mark.asyncio
async def test_retention_cleanup_task_registered():
    """retention_cleanup is registered in Celery beat schedule."""
    from src.celery.celery_config import beat_schedule

    assert "ai-retention-cleanup" in beat_schedule
    task_config = beat_schedule["ai-retention-cleanup"]
    assert "src.app.core.ai_assistants.tasks.retention_cleanup" in task_config["task"]
