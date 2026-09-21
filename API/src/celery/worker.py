from celery.signals import task_prerun, worker_process_init

from celery import Celery
from config import CELERY_ENABLED, COMPOSE_PROJECT_NAME

# Eagerly import ORM models that are referenced by ForeignKey strings in
# other models so SQLAlchemy can resolve them at first metadata use inside
# Celery worker subprocesses. FastAPI loads these transitively via router
# imports at startup; Celery's autodiscover only loads task modules, so
# FK targets like ``integration_dlq.org_id -> organizations.id`` would
# otherwise raise ``NoReferencedTableError`` the first time a task touches
# the DLQ table. Import for side-effects only.
from src.app.core.tenants import models as _tenants_models  # noqa: F401

from . import celery_config as config

celery = Celery(COMPOSE_PROJECT_NAME)
celery.config_from_object(config)
celery.autodiscover_tasks(
    [
        "src.celery.tasks",
        "src.app.core.leads.imports.tasks",
        "src.app.core.contacts.imports.tasks",
        "src.app.core.integrations.google.tasks",
        # tasks/google-calendar-sync Step 4 — per-user Google Calendar
        # sync tasks (hook-triggered sync_appointment_task + 30-min beat
        # reconcile_pending sweep). Without this entry the worker can't
        # resolve the task name enqueued by the appointment CRUD hooks.
        "src.app.core.integrations.google_calendar.tasks",
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
        # tasks/custom-events — hourly sweep at :05 that auto-fires
        # date_field-scheduled custom events (LEAD/appointment/contact)
        # for orgs whose local hour matches the event's ``hour_local``.
        # Without this entry beat enqueues ``sweep_date_triggered_events``
        # and the worker drops it with KeyError, so scheduled events
        # never fire and downstream workflows never run.
        "src.app.core.custom_events.tasks",
        # tasks/automation-engine Step 10 — every-15-min sweep that
        # publishes appointment.reminder_24h + appointment.reminder_1h
        # events for upcoming appointments. Without this entry the beat
        # scheduler can't find the task.
        "src.app.core.appointments.tasks",
        # tasks/automation-engine Step 11 — daily overdue-invoice sweep
        # that publishes invoice.overdue_7d for issued invoices older
        # than 7 days. Without this entry the beat scheduler can't find
        # the task.
        "src.app.core.billing.tasks",
        # tasks/workflows Step 4 — workflow execution engine. Two tasks:
        # process_step (re-enqueued per hop) + sweep_waits (60s beat).
        # Without this entry the engine can't dispatch + parked waits
        # never resume.
        "src.app.core.workflows.tasks",
        # tasks/chatbot-builder — chatbot engine tasks: process_step
        # (re-enqueued per node hop by engine.start_run / advance_run),
        # sweep_chatbot_waits (60s beat), sweep_test_runs (hourly).
        # Without this entry the worker discards every enqueued
        # message as ``KeyError`` and bot runs stay stuck at their
        # first node forever.
        "src.app.core.chatbots.tasks",
        # tasks/dashboard-updates Step 6 — nightly grooming that flips
        # ``open`` tasks whose ``due_at`` is > 7 days ago to ``missed``
        # so the dashboard's Overdue bucket doesn't grow unbounded.
        "src.app.core.tasks.tasks",
        # Module B closing-pass fix — nightly janitor that hard-deletes
        # organizations still stuck in ``template_id='pending'`` more
        # than 48 hours after signup (abandoned onboarding). Without
        # this entry the beat scheduler can't find ``sweep_orphan_
        # pending_orgs`` and the orphan rows accumulate.
        "src.app.core.tenants.tasks",
        # tasks/ai-assistants Step 10 — knowledge ingest pipeline
        # (file / text / url → chunk → embed → upsert). One task:
        # ingest_knowledge, dispatched from the knowledge-upload
        # endpoints. Without this entry the worker can't find the
        # task name and every upload stays stuck at status='pending'.
        "src.app.core.ai_assistants.tasks",
        # tasks/mailgun-inbound Step 3 — Mailgun inbound webhook ingest.
        # ``process_mailgun_inbound`` is dispatched by the webhook after
        # persisting the raw multipart to disk. Without this entry the
        # webhook enqueue silently fails and the pending-inbound
        # sweeper (below) is the only path that clears the on-disk
        # queue — one-tick-slower delivery is fine but the worker MUST
        # know the task name.
        "src.app.core.email.mailgun.tasks",
        # tasks/email-reputation-warmup Step 3 — Mailgun events-webhook
        # ingest. ``process_mailgun_event`` is dispatched by the
        # ``/webhooks/mailgun/events`` endpoint after persisting the raw
        # JSON payload to disk. Without this entry the worker drops the
        # task with a KeyError and 24h counters stop advancing.
        "src.app.core.email.mailgun.events_webhook",
        # tasks/email-reputation-warmup Step 4 — three beats:
        # ``evaluate_warmup_and_shed_4h`` (advance + shed evaluate),
        # ``check_blocked_until_expiry_hourly`` (auto-recovery),
        # ``trim_reputation_buckets_hourly`` (Redis TTL catch-net).
        # Missing entry = beat can't find the tasks and reputation
        # state gets frozen at whatever the events-webhook left behind.
        "src.app.core.email.reputation.tasks",
        # tasks/mailgun-inbound Step 3 — 5-min sweeper that re-enqueues
        # any pending-inbound directory left behind by a broker outage
        # at delivery time. Beat entry lives in celery_config.py.
        "src.app.core.email.mailgun.pending_inbound_sweeper",
        # tasks/mailgun-inbound Step 5 — filesystem orphan sweepers
        # for staging (15-min cadence) + messages/ (daily). Beat
        # entries in celery_config.py.
        "src.app.core.email.mailgun.orphan_cleanup",
        # tasks/email-endpoint-abstraction Step 5 — nightly 03:15 UTC
        # sweep across tbl_channel_endpoints. Soft-deletes rows with
        # no matching details row after 24h and oauth_mailbox rows
        # whose backing tbl_email_accounts has been disconnected for
        # 7d. Without this entry the beat scheduler can't find
        # ``sweep_orphan_endpoints`` and orphan rows accumulate.
        "src.app.core.channel_endpoints.tasks",
        # tasks/email-sending-domains Step 6 — nightly 04:00 UTC
        # re-verify of pending/verified rows + hourly re-verify of
        # demoted rows in tbl_organization_email_domains. Owner is
        # notified on state transitions (verified/demoted/recovered/
        # released). Without this entry both beat sweeps drop with a
        # KeyError and DNS drift goes undetected.
        "src.app.core.email_sender_setup.tasks",
        # tasks/email-quarantine-filters Step 3 — weekly Monday 04:00
        # UTC auto-purge of held quarantine rows older than
        # EMAIL_QUARANTINE_AUTO_PURGE_DAYS (default 30). Without this
        # entry the beat scheduler can't find
        # ``auto_purge_quarantine`` and held rows accumulate forever.
        "src.app.core.email.quarantine.tasks",
    ]
)

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
