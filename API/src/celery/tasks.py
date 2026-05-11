import asyncio
from celery import shared_task
from src.celery.helpers.tasks_collections import run_every_2_minutes, run_every_day


@shared_task
def execute_every_2_minutes():
    asyncio.run(run_every_2_minutes())


@shared_task
def execute_every_day():
    asyncio.run(run_every_day())
