"""Baseline smoke tests for the FitOps backend harness."""

from celery import Celery
from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TestCase

from config import celery_app


class SettingsSmokeTests(SimpleTestCase):
    def test_locked_backend_settings(self):
        expected_apps = {
            "apps.accounts",
            "apps.workspaces",
            "apps.coaching",
            "apps.clients",
            "apps.applications",
            "apps.commerce",
            "apps.billing",
            "apps.notifications",
            "apps.audit",
        }

        self.assertTrue(expected_apps.issubset(settings.INSTALLED_APPS))
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql")


class DatabaseSmokeTests(TestCase):
    def test_database_executes_query(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

        self.assertEqual(result, (1,))


class CeleryConfigurationSmokeTests(SimpleTestCase):
    def test_celery_app_accepts_json_only(self):
        self.assertIsInstance(celery_app, Celery)
        self.assertEqual(celery_app.conf.task_serializer, "json")
        self.assertEqual(celery_app.conf.result_serializer, "json")
        self.assertEqual(celery_app.conf.accept_content, ["json"])
