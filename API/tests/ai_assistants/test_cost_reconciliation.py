"""Cost reconciliation task tests
(``tasks/ai-assistants`` Step 17).

Tests the cost outbox reconciliation logic.
"""

from __future__ import annotations

import pytest

# Side-effect imports for FK resolution
import src.app.core.ai_assistants.models  # noqa: F401,E402


def test_cost_status_has_pending_llm_confirm():
    """CostStatus enum includes ``pending_llm_confirm`` for messages
    awaiting cost validation."""
    from src.app.core.ai_assistants.models import CostStatus

    assert hasattr(CostStatus, 'pending_llm_confirm')
    assert CostStatus.pending_llm_confirm.value == 'pending_llm_confirm'


def test_cost_status_has_reconciled():
    """CostStatus enum includes ``reconciled`` for confirmed costs."""
    from src.app.core.ai_assistants.models import CostStatus

    assert hasattr(CostStatus, 'reconciled')
    assert CostStatus.reconciled.value == 'reconciled'


def test_cost_status_has_failed():
    """CostStatus enum includes ``failed`` for reconciliation failures."""
    from src.app.core.ai_assistants.models import CostStatus

    assert hasattr(CostStatus, 'failed')
    assert CostStatus.failed.value == 'failed'


@pytest.mark.asyncio
async def test_reconcile_cost_outbox_task_registered():
    """reconcile_cost_outbox is registered in Celery beat schedule with
    5-min cadence."""
    from src.celery.celery_config import beat_schedule

    assert "ai-reconcile-cost-outbox" in beat_schedule
    task_config = beat_schedule["ai-reconcile-cost-outbox"]
    assert "src.app.core.ai_assistants.tasks.reconcile_cost_outbox" in task_config["task"]
    assert task_config["schedule"] == 300.0  # 5 minutes in seconds
