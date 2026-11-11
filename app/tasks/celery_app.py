"""Celery worker + beat. Ingestion runs only here or via the CLI, never via public HTTP."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

celery_app = Celery("lexuz", broker=settings.broker_url, backend=None, include=["app.tasks.tasks"])
celery_app.conf.update(
    task_default_queue="ingestion",
    task_acks_late=True,  # a crashed worker's task is redelivered; the pipeline is idempotent
    worker_prefetch_multiplier=1,
    task_time_limit=3 * 3600,
    timezone="Asia/Tashkent",
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # Weekly, low-frequency update check of every pre-approved source.
        "weekly-source-check": {
            "task": "lexuz.check_all_sources",
            "schedule": crontab(hour=4, minute=15, day_of_week="mon"),
        },
    },
)
app = celery_app
