"""Shared Django settings for FitOps."""

import os
from pathlib import Path


def env(name, default=None):
    """Read an environment variable, returning a default when it is unset."""
    return os.environ.get(name, default)


def env_bool(name, default=False):
    """Read an environment variable as a boolean."""
    value = env(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=None):
    """Read a comma-separated environment variable as a list."""
    value = env(name)
    if value is None:
        return list(default or [])
    return [item.strip() for item in value.split(",") if item.strip()]


# --------------------------------------------------------------------
# PATHS
# --------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# --------------------------------------------------------------------
# CORE
# --------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")


# --------------------------------------------------------------------
# APPLICATIONS
# --------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
]
LOCAL_APPS = []  # the nine FitOps apps added in task T3

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


# --------------------------------------------------------------------
# MIDDLEWARE
# --------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# --------------------------------------------------------------------
# URLS / TEMPLATES / WSGI
# --------------------------------------------------------------------
ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --------------------------------------------------------------------
# DATABASE
# --------------------------------------------------------------------
# Configured in task T6 (PostgreSQL from environment).
DATABASES = {}


# --------------------------------------------------------------------
# AUTH / PASSWORD VALIDATION
# --------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --------------------------------------------------------------------
# INTERNATIONALIZATION
# --------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# --------------------------------------------------------------------
# STATIC / MEDIA
# --------------------------------------------------------------------
STATIC_URL = "static/"
# Additional static and media handling is configured in task T8.


# --------------------------------------------------------------------
# SESSIONS & SECURITY
# --------------------------------------------------------------------
# Configured in task T5 (Django sessions and security settings).


# --------------------------------------------------------------------
# EMAIL
# --------------------------------------------------------------------
# Configured in task T7 (Django email backend + SMTP from environment).


# --------------------------------------------------------------------
# REST FRAMEWORK
# --------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.FitOpsPageNumberPagination",
    "PAGE_SIZE": 20,
}
