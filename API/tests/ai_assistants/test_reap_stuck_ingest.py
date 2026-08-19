"""Reap stuck ingest task tests
(``tasks/ai-assistants`` Step 17).

Tests the stuck knowledge row reaper logic.
"""

from __future__ import annotations

import pytest

# Side-effect imports for FK resolution
import src.app.core.ai_assistants.models  # noqa: F401,E402


def test_knowledge_status_has_failed_stuck():
    """KnowledgeStatus enum includes ``failed_stuck`` for workers that
    stopped mid-ingest."""
    from src.app.core.ai_assistants.models import KnowledgeStatus

    assert hasattr(KnowledgeStatus, 'failed_stuck')
    assert KnowledgeStatus.failed_stuck.value == 'failed_stuck'


def test_knowledge_model_has_heartbeat_at():
    """AiAssistantKnowledge has heartbeat_at timestamp column for
    tracking worker activity during ingest."""
    from src.app.core.ai_assistants.models import AiAssistantKnowledge

    assert hasattr(AiAssistantKnowledge, 'heartbeat_at')
    hb_col = AiAssistantKnowledge.__table__.c.heartbeat_at
    assert hb_col.nullable is True  # NULL = never started


@pytest.mark.asyncio
async def test_reap_stuck_ingest_task_registered():
    """reap_stuck_ingest is registered in Celery beat schedule with 5-min cadence."""
    from src.celery.celery_config import beat_schedule

    assert "ai-reap-stuck-ingest" in beat_schedule
    task_config = beat_schedule["ai-reap-stuck-ingest"]
    assert "src.app.core.ai_assistants.tasks.reap_stuck_ingest" in task_config["task"]
    assert task_config["schedule"] == 300.0  # 5 minutes in seconds
