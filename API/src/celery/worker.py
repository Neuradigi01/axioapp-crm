from celery import Celery
from config import COMPOSE_PROJECT_NAME, CELERY_ENABLED
from . import celery_config as config

celery = Celery(COMPOSE_PROJECT_NAME)
celery.config_from_object(config)
celery.autodiscover_tasks(["src.celery.tasks"])

if not CELERY_ENABLED:
    celery.conf.task_always_eager = True
    celery.conf.task_eager_propagates = True
    celery.conf.beat_schedule = {}
