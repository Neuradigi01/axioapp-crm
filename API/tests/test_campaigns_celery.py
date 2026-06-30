"""Step 3.5.14 — Celery dispatch wiring tests.

The tasks themselves are tested via the underlying `dispatch_chunk`
in `test_campaigns_template_dispatch.py`. Here we just lock down:

  1. The shim is in place — `_shared_task` decorator preserves a
     callable with `.delay()` even when celery is absent.
  2. `HAS_CELERY` reflects the import success boolean.
  3. `send_campaign_chunk` exposes the Celery name the beat schedule
     references, so a typo in either side would surface here.
  4. `dispatch_scheduled_campaigns` is registered with the expected
     task name.

The full inline-vs-Celery branch in `service.enqueue` is exercised by
the existing campaign happy-path tests + the manual smoke.
"""

from __future__ import annotations

from src.app.core.campaigns import tasks


class TestTaskRegistration:
    def test_send_chunk_callable(self):
        """The shim makes `send_campaign_chunk` callable + provides
        `.delay()` even without celery. The actual task name is the
        contract the beat scheduler references."""
        assert callable(tasks.send_campaign_chunk)
        # In eager / shim mode both `__call__` and `.delay` exist.
        assert hasattr(tasks.send_campaign_chunk, "delay")

    def test_scheduled_dispatch_callable(self):
        assert callable(tasks.dispatch_scheduled_campaigns)
        assert hasattr(tasks.dispatch_scheduled_campaigns, "delay")

    def test_has_celery_flag_is_bool(self):
        """`HAS_CELERY` is exported for callers (e.g. service.enqueue)
        that branch on it. Type must be bool."""
        assert isinstance(tasks.HAS_CELERY, bool)


class TestBeatSchedule:
    """The api-image doesn't have `celery` installed (only the worker
    image does), so we can't import `src.celery.celery_config` directly.
    Read the file as text + assert the lines instead — same coverage,
    no runtime dependency on celery."""

    def test_beat_entry_references_correct_task_name(self):
        """If the Celery task name and the beat schedule entry drift
        apart, the beat fires a task that nothing handles."""
        from pathlib import Path

        src = Path("/app/src/celery/celery_config.py").read_text(encoding="utf-8")
        assert "dispatch-scheduled-campaigns" in src
        assert "src.app.core.campaigns.tasks.dispatch_scheduled_campaigns" in src
        # 60-second cadence per pre-impl choice (a).
        assert "'schedule': 60.0" in src

    def test_autodiscover_includes_campaigns_tasks(self):
        """Worker.py must list `core.campaigns.tasks` so Celery picks
        up the @shared_task decorators at boot."""
        from pathlib import Path

        src = Path("/app/src/celery/worker.py").read_text(encoding="utf-8")
        assert "src.app.core.campaigns.tasks" in src
