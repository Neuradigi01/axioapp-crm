from celery import Celery
from config import COMPOSE_PROJECT_NAME, CELERY_ENABLED
from . import celery_config as config

celery = Celery(COMPOSE_PROJECT_NAME)
celery.config_from_object(config)
celery.autodiscover_tasks([
    "src.celery.tasks",
    "src.app.core.leads.imports.tasks",
    "src.app.core.integrations.google.tasks",
    "src.app.core.integrations.meta.tasks",
    # Step 3.5.14 — campaign chunk sender + scheduled-campaigns beat.
    "src.app.core.campaigns.tasks",
])

if not CELERY_ENABLED:
    celery.conf.task_always_eager = True
    celery.conf.task_eager_propagates = True
    celery.conf.beat_schedule = {}
