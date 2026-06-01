from urllib.parse import quote_plus
from celery.schedules import crontab
from config import (
    COMPOSE_PROJECT_NAME, REDIS_PASSWORD, TIMEZONE,
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD,
    REDIS_HOST, REDIS_PORT, REDIS_DB_BROKER, REDIS_DB_RESULT,
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
    'task-every-2-minutes': {
        'task': 'src.celery.tasks.execute_every_2_minutes',
        'schedule': 120.0,
    },
    'task-daily': {
        'task': 'src.celery.tasks.execute_every_day',
        'schedule': crontab(hour=0, minute=0),
    },
    # Step 3.5.14 — sweep for scheduled campaigns whose schedule_at
    # has elapsed. 60s cadence; tighter would only matter for sub-
    # minute schedules (not a real operator workflow).
    'dispatch-scheduled-campaigns': {
        'task': 'src.app.core.campaigns.tasks.dispatch_scheduled_campaigns',
        'schedule': 60.0,
    },
    # Step 5 — refresh every lead's lead_score against the active
    # rule set. Per-write recompute already keeps things mostly fresh;
    # this hourly sweep handles the case where an operator edits a
    # rule and we need to apply the new shape org-wide without
    # touching every lead manually. Per-org loop is internal to the
    # task.
    'recompute-all-lead-scores': {
        'task': 'src.app.core.leads.scoring.recompute_all_lead_scores',
        'schedule': crontab(minute=0),
    },
}
