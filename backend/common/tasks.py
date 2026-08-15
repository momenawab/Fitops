"""Shared infrastructure tasks."""

from celery import shared_task


@shared_task
def health_check():
    """Return a minimal serialisable worker health response."""
    return "ok"
