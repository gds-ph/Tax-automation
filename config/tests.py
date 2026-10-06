"""Checks for the foundation's private, loopback-only configuration."""

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import Resolver404, resolve

from config import settings as project_settings


class FoundationTests(SimpleTestCase):
    # The operational logging middleware records a row for every 4xx response,
    # so the request-level checks below need database access.
    databases = {"default"}

    def test_local_configuration(self):
        self.assertEqual(settings.TIME_ZONE, "Asia/Manila")
        self.assertTrue(settings.USE_TZ)
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3")
        # Django's test runner adds "testserver" to the runtime setting.
        self.assertTrue(set(project_settings.ALLOWED_HOSTS) <= {"127.0.0.1", "localhost"})
        self.assertNotEqual(settings.MEDIA_ROOT, settings.STATIC_ROOT)
        self.assertNotIn(settings.MEDIA_ROOT, settings.STATICFILES_DIRS)

    def test_media_has_no_public_route(self):
        for path in ("/media/example.pdf", "/media/example.xml"):
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve(path)

    @override_settings(DEBUG=False)
    def test_anonymous_media_request_returns_not_found(self):
        response = self.client.get("/media/example.pdf", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=False)
    def test_nonlocal_host_is_rejected(self):
        response = self.client.get("/admin/", HTTP_HOST="192.168.14.135")
        self.assertEqual(response.status_code, 400)
