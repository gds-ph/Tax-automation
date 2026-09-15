import io
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import Client, TestCase
from django.urls import reverse

from workorders.models import WorkOrder


class DashboardRoleTests(TestCase):
    def test_three_groups_and_permissions(self):
        expected = {
            "Preparer": {"view_workorder", "add_workorder", "change_workorder", "view_auditevent"},
            "Approver": {"view_workorder", "view_auditevent"},
            "Administrator": {"view_workorder", "add_workorder", "change_workorder", "view_auditevent", "view_agent"},
        }
        views = {"view_prepared_pdf", "view_client", "view_formdefinition", "view_clientfilingprofile", "view_workordersnapshot"}
        writes = {"add_client", "change_client", "add_clientfilingprofile", "change_clientfilingprofile"}
        expected["Preparer"].update(views | writes)
        expected["Approver"].update(views | {"approve_stage2"})
        expected["Administrator"].update(views | writes | {"add_formdefinition", "change_formdefinition", "approve_stage2"})
        for name, permissions in expected.items():
            with self.subTest(group=name):
                self.assertEqual(set(Group.objects.get(name=name).permissions.values_list("codename", flat=True)), permissions)

    def test_role_setup_is_idempotent_and_does_not_elevate_users(self):
        actor = get_user_model().objects.create_user(username="preparer")
        actor.groups.add(Group.objects.get(name="Preparer"))
        migration = import_module("accounts.migrations.0001_dashboard_roles")
        # The data migration only needs the connection alias, not DDL operations.
        migration.create_dashboard_roles(apps, SimpleNamespace(connection=connection))
        actor.refresh_from_db()
        self.assertFalse(actor.is_staff)
        self.assertFalse(actor.is_superuser)
        self.assertEqual(Group.objects.filter(name__in=["Preparer", "Approver", "Administrator"]).count(), 3)
        self.assertTrue(actor.has_perm("workorders.add_workorder"))


class DashboardAuthTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="test_login", password="fake-test-password")
        self.actor.groups.add(Group.objects.get(name="Preparer"))

    def test_login_logout_and_safe_redirect(self):
        response = self.client.post(reverse("login"), {"username": "test_login", "password": "fake-test-password"})
        self.assertRedirects(response, reverse("workorders:clients"))
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.post(reverse("login"), {"username": "test_login", "password": "fake-test-password", "next": "https://example.invalid/"})
        self.assertRedirects(response, reverse("workorders:clients"))

    def test_login_preserves_safe_local_next(self):
        response = self.client.post(reverse("login"), {"username": "test_login", "password": "fake-test-password", "next": "/work-orders/"})
        self.assertRedirects(response, "/work-orders/")

    def test_invalid_or_inactive_login_rejected(self):
        response = self.client.post(reverse("login"), {"username": "test_login", "password": "wrong"})
        self.assertContains(response, "Sign-in failed")
        self.actor.is_active = False
        self.actor.save()
        self.client.post(reverse("login"), {"username": "test_login", "password": "fake-test-password"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_and_logout_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse("login"), {"username": "test_login", "password": "fake-test-password"}).status_code, 403)
        client.force_login(self.actor)
        self.assertEqual(client.post(reverse("logout")).status_code, 403)

    def test_authenticated_login_redirects_to_filings(self):
        self.client.force_login(self.actor)
        self.assertRedirects(self.client.get(reverse("login")), reverse("workorders:clients"))

    def test_unassigned_user_sees_access_guidance(self):
        user = get_user_model().objects.create_user(username="no_role")
        self.client.force_login(user)
        response = self.client.get(reverse("workorders:clients"))
        self.assertContains(response, "assign the appropriate workspace role", status_code=403)


class DemoCommandTests(TestCase):
    def test_seed_demo_is_opt_in_fake_and_idempotent(self):
        user = get_user_model().objects.create_user(username="demo_actor")
        user.groups.add(Group.objects.get(name="Preparer"))
        self.assertEqual(WorkOrder.objects.count(), 0)
        stream = io.StringIO()
        call_command("seed_demo", actor=user.username, stdout=stream)
        call_command("seed_demo", actor=user.username, stdout=stream)
        self.assertEqual(WorkOrder.objects.count(), 3)
        self.assertEqual(WorkOrder.objects.filter(status="READY_TO_PREPARE").count(), 1)
        for order in WorkOrder.objects.all():
            self.assertTrue(order.client_name.startswith("FAKE DEMO"))
            self.assertTrue(order.email_address.endswith("@example.invalid"))
            self.assertEqual(order.atc_code, "PT 010")

    def test_seed_demo_rejects_unauthorized_actor(self):
        user = get_user_model().objects.create_user(username="no_access")
        with self.assertRaises(CommandError):
            call_command("seed_demo", actor=user.username, stdout=io.StringIO())
        self.assertEqual(WorkOrder.objects.count(), 0)
