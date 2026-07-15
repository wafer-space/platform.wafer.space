"""
Celery configuration for wafer.space platform.
"""

from __future__ import annotations

import logging
import os

from celery import Celery
from celery.signals import task_failure

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("wafer_space")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django apps.
app.autodiscover_tasks()


@task_failure.connect
def report_task_failure(
    sender: object | None = None,
    task_id: str | None = None,
    exception: BaseException | None = None,
    einfo: object | None = None,
    **kwargs: object,
) -> None:
    """Log unhandled task failures under the wafer_space logger tree.

    Celery's own failure logging goes to the root logger, which only
    reaches the console/worker logfile. Re-logging under "wafer_space."
    routes unhandled task exceptions through the same handlers as
    application errors - in prod/stage that includes the rate-limited
    ADMINS email handler (issue #293).
    """
    logging.getLogger("wafer_space.celery").error(
        "Celery task %s[%s] failed: %s",
        getattr(sender, "name", sender),
        task_id,
        exception,
        exc_info=getattr(einfo, "exc_info", None),
    )


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task for testing Celery configuration."""
    logger = logging.getLogger(__name__)
    logger.info("Request: %r", self.request)
