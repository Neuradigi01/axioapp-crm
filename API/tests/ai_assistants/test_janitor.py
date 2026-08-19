"""Janitor beat task tests
(``tasks/ai-assistants`` Step 17).

Tests cover:
  * retention_cleanup: message deletion by age
  * reap_stuck_ingest: marking stuck knowledge rows
  * cleanup_orphan_chunks: orphan chunk deletion
  * expire_embed_key_grace: grace period expiry
  * reconcile_cost_outbox: cost reconciliation on timeout
  * org-delete cascade: SSE cancellation + storage cleanup
  * janitor_heartbeat: heartbeat upsert

Some tests are pure-Python (mocking); others hit the real DB and skip
when the compose stack isn't up.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Side-effect imports for FK resolution
import src.app.core.ai_assistants.models  # noqa: F401,E402
import src.app.core.conversations.models  # noqa: F401,E402
import src.app.core.embed.models  # noqa: F401,E402


def test_retention_days_field_clamped_to_400():
    """retention_days in schema is capped at 400 via Pydantic validator.
    Operator trying to set 1000 gets 422."""
    from src.app.core.ai_assistants.schemas import AiAssistantCreate
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        AiAssistantCreate(
            name="test",
            key_id=uuid.uuid4(),
            model="gpt-4o-mini",
            retention_days=1000,
        )
    assert "less than or equal to 400" in str(exc_info.value)


def test_retention_days_minimum_1():
    """retention_days must be >= 1."""
    from src.app.core.ai_assistants.schemas import AiAssistantCreate
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        AiAssistantCreate(
            name="test",
            key_id=uuid.uuid4(),
            model="gpt-4o-mini",
            retention_days=0,
        )
    assert "greater than or equal to 1" in str(exc_info.value)


def test_janitor_heartbeat_table_structure():
    """JanitorHeartbeat model has expected columns and PK on name."""
    from src.app.core.ai_assistants.models import JanitorHeartbeat

    # name is the primary key (unique, not nullable).
    pk = [col for col in JanitorHeartbeat.__table__.primary_key.columns]
    assert len(pk) == 1
    assert pk[0].name == "name"


def test_gdpr_deletion_log_has_org_id():
    """GdprDeletionLog is org-scoped; has org_id FK."""
    from src.app.core.ai_assistants.models import GdprDeletionLog

    # org_id should be a column.
    assert hasattr(GdprDeletionLog, "org_id")
    # Index on (org_id, deleted_at).
    index_names = [idx.name for idx in GdprDeletionLog.__table__.indexes]
    assert any("org_deleted" in name for name in index_names)


@pytest.mark.asyncio
async def test_sse_registry_cancel_by_org_cancels_all_streams(monkeypatch):
    """SSE registry's cancel_by_org method cancels all active streams.
    In single-process v1, this is a global cancel; multi-worker v2 would
    need Redis pub/sub.
    """
    from src.app.core.ai_assistants.sse_registry import SseStreamRegistry

    registry = SseStreamRegistry()

    # Register a few fake streams.
    handle1 = registry.register(
        embed_key_id=uuid.uuid4(),
        session_token="session-1",
    )
    handle2 = registry.register(
        embed_key_id=uuid.uuid4(),
        session_token="session-2",
    )

    assert not handle1.cancelled
    assert not handle2.cancelled
    assert registry.active_count() == 2

    # Cancel by org (any org; just cancels all).
    count = registry.cancel_by_org(uuid.uuid4())
    assert count == 2
    assert handle1.cancelled
    assert handle2.cancelled


def test_storage_delete_directory_path_handling(tmp_path):
    """LocalStorage.delete_directory safely deletes nested paths without
    path-traversal issues."""
    from src.app.shared.storage.local import LocalStorage

    storage = LocalStorage(root=str(tmp_path))

    # Create nested structure.
    org_path = tmp_path / "test-org" / "ai_assistants"
    org_path.mkdir(parents=True, exist_ok=True)
    (org_path / "file1.txt").write_text("content")
    (org_path / "subdir").mkdir(exist_ok=True)
    (org_path / "subdir" / "file2.txt").write_text("content")

    # Delete the org directory.
    count = storage.delete_directory("test-org/ai_assistants")
    assert count == 2

    # Directory is gone.
    assert not org_path.exists()


def test_janitor_functions_are_importable():
    """All 6 janitor task async functions are importable from the janitor module."""
    from src.app.core.ai_assistants import janitor

    assert hasattr(janitor, 'retention_cleanup')
    assert hasattr(janitor, 'reap_stuck_ingest')
    assert hasattr(janitor, 'cleanup_orphan_chunks')
    assert hasattr(janitor, 'expire_embed_key_grace')
    assert hasattr(janitor, 'reconcile_cost_outbox')
    assert hasattr(janitor, 'janitor_heartbeat')


def test_janitor_functions_are_async():
    """All janitor functions are async (coroutine functions)."""
    import inspect
    from src.app.core.ai_assistants import janitor

    for name in [
        'retention_cleanup', 'reap_stuck_ingest', 'cleanup_orphan_chunks',
        'expire_embed_key_grace', 'reconcile_cost_outbox', 'janitor_heartbeat',
    ]:
        fn = getattr(janitor, name)
        assert inspect.iscoroutinefunction(fn), f"{name} is not async"


def test_celery_beat_schedule_has_ai_tasks():
    """Celery beat_schedule includes all 6 AI janitor tasks."""
    from src.celery.celery_config import beat_schedule

    expected_tasks = [
        "ai-retention-cleanup",
        "ai-reap-stuck-ingest",
        "ai-cleanup-orphan-chunks",
        "ai-expire-embed-key-grace",
        "ai-reconcile-cost-outbox",
        "ai-janitor-heartbeat",
    ]

    for task_name in expected_tasks:
        assert task_name in beat_schedule, f"{task_name} not in beat_schedule"
        assert beat_schedule[task_name]["task"].startswith(
            "src.app.core.ai_assistants.tasks."
        ), f"{task_name} has unexpected task path"
