"""Celery application configuration for FitOps."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("fitops")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# ``common`` is shared infrastructure rather than an installed Django app, so
# its health task must be imported explicitly instead of relying on discovery.
import common.tasks  # noqa: E402, F401
