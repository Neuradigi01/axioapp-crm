from celery import Celery
from celery.signals import task_prerun, worker_process_init
from config import COMPOSE_PROJECT_NAME, CELERY_ENABLED
from . import celery_config as config

# Eagerly import ORM models that are referenced by ForeignKey strings in
# other models so SQLAlchemy can resolve them at first metadata use inside
# Celery worker subprocesses. FastAPI loads these transitively via router
# imports at startup; Celery's autodiscover only loads task modules, so
# FK targets like ``integration_dlq.org_id -> organizations.id`` would
# otherwise raise ``NoReferencedTableError`` the first time a task touches
# the DLQ table. Import for side-effects only.
from src.app.core.tenants import models as _tenants_models  # noqa: F401

celery = Celery(COMPOSE_PROJECT_NAME)
celery.config_from_object(config)
celery.autodiscover_tasks([
    "src.celery.tasks",
    "src.app.core.leads.imports.tasks",
    "src.app.core.integrations.google.tasks",
    "src.app.core.integrations.meta.tasks",
    # Step 3.5.14 — campaign chunk sender + scheduled-campaigns beat.
    "src.app.core.campaigns.tasks",
    # Pricing-and-Billing Step 5 — usage-counter rollover + daily reset.
    "src.app.core.subscriptions.tasks",
    # App-updates Email Step 4 — mailbox sync daemon (backfill,
    # incremental, renewal, poll fallback, daily counter reset).
    "src.app.core.email.tasks",
    # App-updates Email Step 7 — sequence scheduler tick (every 60s).
    "src.app.core.email_sequences.tasks",
    # whatsapp-platform-upgrade Step 12 — hourly phone-health refresh.
    "src.app.core.integrations.whatsapp.health_tasks",
    # tasks/template-library Step 14 — hourly external-status sync for
    # WA templates. Without this entry the beat-scheduled task lands
    # in the worker with `KeyError: 'src.app.core.templates.tasks.
    # sync_external_status_all'` because autodiscover doesn't reach it.
    "src.app.core.templates.tasks",
    # tasks/automation-engine Step 4 — deliver_run task fires once
    # per queued automation run. The dispatcher .apply_async()'s the
    # run id; without this entry the worker can't find the task.
    "src.app.core.automation.tasks",
])

if not CELERY_ENABLED:
    celery.conf.task_always_eager = True
    celery.conf.task_eager_propagates = True
    celery.conf.beat_schedule = {}


@worker_process_init.connect
def _reset_db_engine_in_worker(**_kwargs) -> None:
    """Dispose the async DB engine inherited from the prefork parent.

    SQLAlchemy's async engine is created at module import in the parent
    process. Prefork copies open asyncpg connections to each worker
    subprocess, but the parent still owns the file descriptors — so any
    query in the worker raises ``InterfaceError: cannot perform operation:
    another operation is in progress``. Disposing the engine here drops
    the inherited connections; new ones are opened lazily inside each
    task with no cross-process aliasing.
    """
    import asyncio

    from src.core.db import engine as _engine

    try:
        asyncio.run(_engine.dispose())
    except RuntimeError:
        # If an event loop is somehow already running in this subprocess
        # (shouldn't happen at init time), fall back to sync dispose. The
        # async dispose is a nicety; sync still drops the pool.
        _engine.sync_engine.dispose()


@task_prerun.connect
def _reset_db_engine_per_task(**_kwargs) -> None:
    """Drop cached connections before each task so it starts with a fresh pool.

    Each Celery task wraps its async work in ``asyncio.run(...)`` which spins
    up a new event loop and tears it down on return. Connections cached in
    the SQLAlchemy pool from a previous task's loop are bound to that dead
    loop's selectors — reusing them on the next task raises ``RuntimeError:
    ... got Future ... attached to a different loop`` or asyncpg's
    ``InterfaceError: cannot perform operation: another operation is in
    progress``. We must dispose via the async API (``await engine.dispose()``)
    so asyncpg can properly close each socket; the sync fallback leaks them.
    """
    import asyncio

    from src.core.db import engine as _engine

    try:
        asyncio.run(_engine.dispose())
    except Exception:
        # Best-effort sync fallback — the next .connect() call will still
        # try to hand the task a fresh connection even if dispose hiccups.
        try:
            _engine.sync_engine.dispose()
        except Exception:
            pass
