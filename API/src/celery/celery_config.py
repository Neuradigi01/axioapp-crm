from urllib.parse import quote_plus

from celery.schedules import crontab

from config import (
    COMPOSE_PROJECT_NAME,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    REDIS_DB_BROKER,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
    TIMEZONE,
)

broker_url = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_BROKER}"
result_backend = f"db+postgresql://{DB_USER}:{quote_plus(DB_PASSWORD or '')}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode=disable"
task_default_queue = f"{COMPOSE_PROJECT_NAME}_queue"
task_serializer = "json"
accept_content = ["json"]
timezone = TIMEZONE
enable_utc = True
task_time_limit = 300
task_soft_time_limit = 240

beat_schedule = {
    "task-every-2-minutes": {
        "task": "src.celery.tasks.execute_every_2_minutes",
        "schedule": 120.0,
    },
    "task-daily": {
        "task": "src.celery.tasks.execute_every_day",
        "schedule": crontab(hour=0, minute=0),
    },
    # Step 3.5.14 — sweep for scheduled campaigns whose schedule_at
    # has elapsed. 60s cadence; tighter would only matter for sub-
    # minute schedules (not a real operator workflow).
    "dispatch-scheduled-campaigns": {
        "task": "src.app.core.campaigns.tasks.dispatch_scheduled_campaigns",
        "schedule": 60.0,
    },
    # Step 5 — refresh every lead's lead_score against the active
    # rule set. Per-write recompute already keeps things mostly fresh;
    # this hourly sweep handles the case where an operator edits a
    # rule and we need to apply the new shape org-wide without
    # touching every lead manually. Per-org loop is internal to the
    # task.
    "recompute-all-lead-scores": {
        "task": "src.app.core.leads.scoring.recompute_all_lead_scores",
        "schedule": crontab(minute=0),
    },
    # Pricing-and-Billing Step 5 — advance each subscription's billing
    # window past its current_period_end and insert fresh zeroed
    # `monthly` usage-counter rows for the new period. Hourly cadence
    # at minute=5 to offset from the lead-score job at minute=0 so the
    # two heavy sweeps don't contend on the DB pool.
    "subscriptions-rollover-period-counters": {
        "task": "src.app.core.subscriptions.tasks.rollover_period_counters",
        "schedule": crontab(minute=5),
    },
    # Pricing-and-Billing Step 5 — open the next UTC day's `daily`
    # counter rows (today only `api_calls_per_day`). Runs once at
    # 00:00 UTC.
    "subscriptions-reset-daily-counters": {
        "task": "src.app.core.subscriptions.tasks.reset_daily_counters",
        "schedule": crontab(hour=0, minute=0),
    },
    # Pricing-and-Billing Step 6 — advance trial / read_only / archived
    # subscriptions past their deadlines and fire the 3-day "trial
    # ending soon" reminder. Hourly at minute=10 to offset from the
    # period-rollover (minute=5) and lead-score recompute (minute=0).
    "subscriptions-advance-trial-lifecycle": {
        "task": "src.app.core.subscriptions.tasks.advance_trial_lifecycle",
        "schedule": crontab(minute=10),
    },
    # App-updates Email Step 4 — every 60s, sweep for live accounts
    # whose last_sync_at is older than 5 minutes and enqueue an
    # incremental sync. Covers accounts without push configured AND
    # accounts whose push briefly dropped notifications.
    "email-poll-fallback": {
        "task": "src.app.core.email.tasks.poll_fallback",
        "schedule": 60.0,
    },
    # workflows-absorb-automation follow-up (2026-08-05) — sweep for
    # email_accounts stuck in sync_state='pending' > 5 minutes after
    # connect. Recovers accounts whose initial `enqueue_backfill` fired
    # into a temporarily-blipped broker (fire-and-forget swallows the
    # ConnectionError). Without this sweep the account sits at
    # `pending` forever + workflow email sends skip with
    # `org_sender_not_configured` + the operator has to click
    # Reconnect (or admin has to hand-flip the DB row). Runs every 60s
    # to match `email-poll-fallback`; cheap query (indexed on
    # sync_state + partial where clause on pending).
    "email-sweep-stuck-pending": {
        "task": "src.app.core.email.tasks.sweep_stuck_pending",
        "schedule": 60.0,
    },
    # App-updates Email Step 4 — every 30 min, enqueue watch /
    # subscription renewals for accounts that haven't synced in
    # 2 days (Microsoft) / 5 days (Gmail). Cheap idempotent calls;
    # better to over-renew than to let a watch expire silently.
    "email-scan-renewals": {
        "task": "src.app.core.email.tasks.scan_renewals",
        "schedule": crontab(minute="*/30"),
    },
    # App-updates Email Step 4 — midnight UTC, zero every account's
    # daily_sent_count + stamp daily_sent_reset_at. Idempotent.
    "email-reset-daily-sent-counters": {
        "task": "src.app.core.email.tasks.reset_daily_sent_counters",
        "schedule": crontab(hour=0, minute=0),
    },
    # App-updates Email Step 7 — every 60s, sweep due
    # `email_sequence_enrollment_steps` rows, render their templates,
    # and dispatch via the Step 5 send_email entry point. Reply
    # detection auto-pauses enrollments where the contact replied;
    # 200-rows/tick cap bounds wall-clock and stays well within
    # Gmail/Microsoft rate limits.
    "email-sequences-tick": {
        "task": "src.app.core.email_sequences.tasks.tick_email_sequences",
        "schedule": 60.0,
    },
    # whatsapp-platform-upgrade Step 12 — hourly per-org phone-health
    # refresh. One Graph API call per connected org per hour, well
    # inside Meta's per-token rate limit. Offset to minute=20 so it
    # doesn't contend with the other hourly sweeps.
    "whatsapp-phone-health-refresh": {
        "task": "src.app.core.integrations.whatsapp.health_tasks.refresh_phone_health_all_orgs",
        "schedule": crontab(minute=20),
    },
    # tasks/template-library Step 14 — every-2-min per-org sweep that
    # re-asks Meta for the current status of every pending / paused
    # central template. Webhook coverage is the primary path; this
    # sweep is the safety net for missed events AND the primary
    # freshness path for the editor (the UI polls the DB while a
    # template is pending, so the sweep cadence bounds how quickly
    # the editor's status badge flips). Only orgs with pending /
    # paused templates are touched — an org whose templates are all
    # approved/archived costs zero Meta calls.
    "templates-sync-external-status": {
        "task": "src.app.core.templates.tasks.sync_external_status_all",
        "schedule": crontab(minute="*/2"),
    },
    # tasks/automation-engine Step 10 — every-15-minute sweep across
    # tbl_appointments that publishes appointment.reminder_24h and
    # appointment.reminder_1h events for rows whose scheduled_at
    # falls inside the matching ±30min bracket. The dispatcher's
    # (trigger_id, event_id) uniqueness absorbs the bracket overlap
    # between ticks so a given appointment fires each reminder at
    # most once.
    "appointments-scan-for-reminders": {
        "task": "src.app.core.appointments.tasks.scan_for_reminders",
        "schedule": crontab(minute="*/15"),
    },
    # tasks/automation-engine Step 11 — daily 9:00 UTC sweep across
    # tbl_invoices that publishes invoice.overdue_7d for any
    # `issued` invoice whose issued_at is more than 7 days ago. The
    # deterministic event_id (`invoice_overdue_7d:{invoice_id}`)
    # dedupes daily ticks so each invoice gets at most one fire.
    "billing-scan-for-overdue": {
        "task": "src.app.core.billing.tasks.scan_for_overdue",
        "schedule": crontab(hour=9, minute=0),
    },
    # tasks/automation-engine Step 12 — daily 03:30 UTC (~9am IST)
    # sweep that publishes contact.birthday for today's birthdays +
    # lead.stale_30d for every active lead with no activity in 30d.
    # event_id idempotency (year-stamped birthdays, first-stale-date
    # stamped staleness) means re-running the task is a no-op.
    "automation-daily-time-based-scan": {
        "task": "src.app.core.automation.tasks.daily_time_based_scan",
        "schedule": crontab(hour=3, minute=30),
    },
    # tasks/workflows Step 4 — every-60s sweep that re-dispatches
    # parked wait-node runs whose next_step_at <= now(). Matches the
    # email-sequences-tick cadence (60s) — same operator-visible
    # responsiveness for time-based hops.
    "workflows-sweep-waits": {
        "task": "src.app.core.workflows.tasks.sweep_waits",
        "schedule": 60.0,
    },
    # tasks/chatbot-builder Step 6 — hourly cleanup of test-fire
    # ChatbotRun rows older than 24h. Case #22 / Decision §17.
    "chatbots-sweep-test-runs": {
        "task": "src.app.core.chatbots.tasks.sweep_test_runs",
        "schedule": crontab(minute=15),
    },
    # tasks/chatbot-builder Step 9 — every-60s sweep that resumes
    # parked chatbot runs whose ``next_step_at <= now()``. Handles
    # both delay-node expiry and Ask-* 22h timeout in one tick.
    "chatbots-sweep-waits": {
        "task": "src.app.core.chatbots.tasks.sweep_chatbot_waits",
        "schedule": 60.0,
    },
    # tasks/workflows Step 11 — every-2-min sweep that fires the
    # ``timeout`` outbound edge on parked ``flow_control.wait_for_event``
    # nodes whose ``expires_at`` has lapsed. Distinct from the
    # sweep_waits sweep above (which handles fixed-delay waits) —
    # the wait_for_event path lives on tbl_workflow_event_waits.
    "workflows-expire-waits": {
        "task": "src.app.core.workflows.tasks.expire_waits",
        "schedule": crontab(minute="*/2"),
    },
    # tasks/workflows Step 18 — hourly sweep that picks A/B-test
    # winners after the holdback elapses. Inconclusive results
    # auto-extend the holdback by 50% (capped at 30 days total).
    "workflows-evaluate-ab": {
        "task": "src.app.core.workflows.tasks.evaluate_ab_winners",
        "schedule": crontab(minute=0),
    },
    # tasks/workflows Step 19 — refresh per-workflow
    # ``cached_running_count`` + ``cached_completed_today_count``
    # so the list page's mini-stats render without per-row aggregate
    # queries. Best-effort; the full analytics endpoint queries live.
    "workflows-refresh-cached-counters": {
        "task": "src.app.core.workflows.tasks.refresh_workflow_cached_counters",
        "schedule": crontab(minute="*/5"),
    },
    # tasks/google-calendar-sync Step 4b — reconciliation safety net.
    # Every 30 min, walk future appointments whose assignees have
    # connected Google Calendar but whose ``google_calendar_event_id``
    # is still NULL, and fire a sync per row. Catches drift from
    # Celery-down periods, dev restarts, or hook dispatch failures
    # (Redis blip, task registration mismatch, etc.).
    "google-calendar-reconcile": {
        "task": "src.app.core.integrations.google_calendar.tasks.reconcile_pending",
        "schedule": crontab(minute="*/30"),
    },
    # tasks/dashboard-updates Step 6 — daily 02:00 UTC sweep across
    # tbl_tasks that flips ``open`` rows whose ``due_at`` is more than
    # 7 days in the past to the terminal ``missed`` status. Bounds the
    # dashboard's Overdue bucket and preserves the audit trail under
    # the Missed filter. 7-day threshold means the ±14h timezone slack
    # (org-local vs UTC) never matters.
    "tasks-groom-stale-open": {
        "task": "src.app.core.tasks.tasks.groom_stale_open_tasks",
        "schedule": crontab(hour=2, minute=0),
    },
    # Module B closing-pass fix — daily 03:45 UTC sweep across
    # tbl_organizations that hard-deletes orgs still in
    # ``template_id='pending'`` more than 48 hours after signup. Users
    # who registered but abandoned the onboarding picker leave those
    # rows behind along with a ``trialing`` subscription and stale
    # ``tbl_auth_sessions`` — none of which will ever activate. Freed
    # emails also let the same person retry signup cleanly. Offset from
    # the other daily sweeps at hour=0/2/3:30 so the DB pool isn't
    # contended.
    "tenants-sweep-orphan-pending-orgs": {
        "task": "src.app.core.tenants.tasks.sweep_orphan_pending_orgs",
        "schedule": crontab(hour=3, minute=45),
    },
    # tasks/workflow-scheduling Step 6 — weekly cleanup for schedule
    # rows whose parent workflow is missing. FK CASCADE should
    # prevent it; this is the safety net for historical drift. Sunday
    # 03:00 UTC = quietest window across the tz mix.
    "workflows-sweep-orphan-schedules-weekly": {
        "task": "src.app.core.workflows.tasks.sweep_orphan_schedules_weekly",
        "schedule": crontab(hour=3, minute=0, day_of_week="sun"),
    },
    # tasks/ai-assistants Step 17 — janitor beat tasks for retention,
    # reaping, grace expiry, and cost reconciliation. Offset each task to
    # stagger DB load across the hour and minimize contention.
    "ai-retention-cleanup": {
        "task": "src.app.core.ai_assistants.tasks.retention_cleanup",
        "schedule": crontab(hour="*/6", minute=5),
    },
    "ai-reap-stuck-ingest": {
        "task": "src.app.core.ai_assistants.tasks.reap_stuck_ingest",
        "schedule": 300.0,  # every 5 minutes
    },
    "ai-cleanup-orphan-chunks": {
        "task": "src.app.core.ai_assistants.tasks.cleanup_orphan_chunks",
        "schedule": crontab(minute=15),
    },
    "ai-expire-embed-key-grace": {
        "task": "src.app.core.ai_assistants.tasks.expire_embed_key_grace",
        "schedule": crontab(minute=25),
    },
    "ai-reconcile-cost-outbox": {
        "task": "src.app.core.ai_assistants.tasks.reconcile_cost_outbox",
        "schedule": 300.0,  # every 5 minutes
    },
    "ai-janitor-heartbeat": {
        "task": "src.app.core.ai_assistants.tasks.janitor_heartbeat",
        "schedule": 60.0,  # every 1 minute
    },
    # tasks/mailgun-inbound Step 3 — every 5 min, re-enqueue any
    # pending-inbound directory older than 5 minutes. Covers the case
    # where the webhook returned 200 but the Celery broker was down
    # at delivery time (payload lives on disk regardless of broker
    # health). Threshold matches beat cadence: a directory is either
    # enqueued at write-time OR picked up on the next beat, never both.
    "mailgun-sweep-pending-inbound": {
        "task": "src.app.core.email.mailgun.pending_inbound_sweeper.sweep_pending_inbound",
        "schedule": 300.0,
    },
    # tasks/mailgun-inbound Step 5 — 15-min sweep of staged-but-
    # never-committed attachment dirs older than 1h. Cheap.
    "mailgun-sweep-staging-orphans": {
        "task": "src.app.core.email.mailgun.orphan_cleanup.sweep_staging_orphans",
        "schedule": crontab(minute="*/15"),
    },
    # tasks/mailgun-inbound Step 5 — daily sweep of messages/{id}/
    # dirs with no matching row (rare rollback / manual delete path).
    # Runs at 04:00 UTC to offset other daily janitor jobs.
    "mailgun-sweep-messages-orphans": {
        "task": "src.app.core.email.mailgun.orphan_cleanup.sweep_messages_orphans",
        "schedule": crontab(hour=4, minute=0),
    },
}
