"""Janitor monitoring tests
(``tasks/ai-assistants`` Step 17).

Tests the janitor heartbeat and GDPR deletion log.
"""

from __future__ import annotations

import pytest

# Side-effect imports for FK resolution
import src.app.core.ai_assistants.models  # noqa: F401,E402


def test_janitor_heartbeat_table_structure():
    """JanitorHeartbeat has name (PK), last_run_at, last_run_status,
    last_error columns."""
    from src.app.core.ai_assistants.models import JanitorHeartbeat

    table = JanitorHeartbeat.__table__
    assert 'name' in table.c
    assert 'last_run_at' in table.c
    assert 'last_run_status' in table.c
    assert 'last_error' in table.c

    # name is primary key (only one).
    pk_cols = list(table.primary_key.columns)
    assert len(pk_cols) == 1
    assert pk_cols[0].name == 'name'


def test_gdpr_deletion_log_is_org_scoped():
    """GdprDeletionLog has org_id FK and is TenantScoped."""
    from src.app.core.ai_assistants.models import GdprDeletionLog
    from src.app.shared.orm import TenantScoped

    assert issubclass(GdprDeletionLog, TenantScoped)
    assert hasattr(GdprDeletionLog, 'org_id')


def test_gdpr_deletion_log_structure():
    """GdprDeletionLog has all expected columns."""
    from src.app.core.ai_assistants.models import GdprDeletionLog

    table = GdprDeletionLog.__table__
    expected_cols = [
        'id', 'org_id', 'entity_type', 'entity_count',
        'id_hash_sha256', 'deletion_reason', 'deleted_at'
    ]
    for col in expected_cols:
        assert col in table.c, f"Missing column: {col}"


@pytest.mark.asyncio
async def test_janitor_heartbeat_task_registered():
    """janitor_heartbeat is registered in Celery beat schedule with
    1-min cadence."""
    from src.celery.celery_config import beat_schedule

    assert "ai-janitor-heartbeat" in beat_schedule
    task_config = beat_schedule["ai-janitor-heartbeat"]
    assert "src.app.core.ai_assistants.tasks.janitor_heartbeat" in task_config["task"]
    assert task_config["schedule"] == 60.0  # 1 minute in seconds


@pytest.mark.asyncio
async def test_cleanup_orphan_chunks_task_registered():
    """cleanup_orphan_chunks is registered in Celery beat schedule."""
    from src.celery.celery_config import beat_schedule

    assert "ai-cleanup-orphan-chunks" in beat_schedule
    task_config = beat_schedule["ai-cleanup-orphan-chunks"]
    assert "src.app.core.ai_assistants.tasks.cleanup_orphan_chunks" in task_config["task"]
