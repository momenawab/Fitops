"""Local-development settings for FitOps."""

from .base import *  # noqa: F403


SECRET_KEY = env(  # noqa: F405
    "DJANGO_SECRET_KEY",
    "django-insecure-fitops-development-only-key",
)
DEBUG = env_bool("DJANGO_DEBUG", True)  # noqa: F405
ALLOWED_HOSTS = env_list(  # noqa: F405
    "DJANGO_ALLOWED_HOSTS",
    ["localhost", "127.0.0.1"],
)

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Print emails to stdout — developers need no SMTP server.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
