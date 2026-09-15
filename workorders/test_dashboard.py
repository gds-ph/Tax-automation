from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.db import OperationalError
from django.test import Client, TestCase
from django.urls import reverse

from .models import WorkOrder
from .services import edit_work_order, transition_work_order
from .test_support import legacy_test_fixture_order as create_work_order, make_profile
from .test_support import fake_data


class DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.preparer = User.objects.create_user(username="test_preparer")
        cls.approver = User.objects.create_user(username="test_approver")
        cls.administrator = User.objects.create_user(username="test_administrator")
        cls.unassigned = User.objects.create_user(username="test_unassigned")
        for user, role in ((cls.preparer, "Preparer"), (cls.approver, "Approver"), (cls.administrator, "Administrator")):
            user.groups.add(Group.objects.get(name=role))
        cls.order = create_work_order(actor=cls.preparer, data=fake_data(client_name="FAKE ALPHA"))

    def post_data(self, **changes):
        source = {key: changes.pop(key) for key in list(changes) if key in {"client_name", "rdo_code"}}
        if "client_name" in source:
            source["trade_name"] = source.pop("client_name")
        profile = make_profile(self.preparer, client_data=source)
        return {**dict(client_filing_profile=str(profile.pk), filing_year="2026", filing_quarter=3, zero_filing=True, atc_code="PT 010"), **changes}

    def setUp(self):
        self.client.force_login(self.preparer)

    def test_all_dashboard_pages_require_login(self):
        self.client.logout()
        for name, kwargs in (("filing-types", {}), ("home", {}), ("list", {}), ("create", {}),
                             ("filing-orders", {"filing_slug": "2551q"}), ("filing-create", {"filing_slug": "2551q"}),
                             ("detail", {"pk": self.order.pk}), ("edit", {"pk": self.order.pk})):
            with self.subTest(name=name):
                response = self.client.get(reverse(f"workorders:{name}", kwargs=kwargs))
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith("/login/?next="))
                self.assertNotContains(response, "FAKE ALPHA", status_code=302)

    def test_unassigned_user_cannot_read_or_write(self):
        self.client.force_login(self.unassigned)
        for name, kwargs in (("filing-types", {}), ("list", {}), ("create", {}), ("detail", {"pk": self.order.pk}), ("edit", {"pk": self.order.pk})):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"workorders:{name}", kwargs=kwargs)).status_code, 403)
        for name in ("ready", "draft"):
            self.assertEqual(self.client.post(reverse(f"workorders:{name}", args=[self.order.pk]), {"expected_version": 1}).status_code, 403)

    def test_all_roles_can_view_and_responses_are_not_cached(self):
        for user in (self.preparer, self.approver, self.administrator):
            self.client.force_login(user)
            for name, kwargs in (("filing-types", {}), ("list", {}), ("detail", {"pk": self.order.pk})):
                with self.subTest(user=user.username, page=name):
                    response = self.client.get(reverse(f"workorders:{name}", kwargs=kwargs))
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("no-store", response.headers["Cache-Control"])

    def test_approver_is_read_only(self):
        self.client.force_login(self.approver)
        response = self.client.get(reverse("workorders:detail", args=[self.order.pk]))
        self.assertNotContains(response, "Edit work order")
        self.assertNotContains(response, "Mark ready to prepare")
        self.assertEqual(self.client.get(reverse("workorders:create")).status_code, 403)
        self.assertEqual(self.client.post(reverse("workorders:create"), self.post_data()).status_code, 403)
        for name in ("edit", "ready", "draft"):
            self.assertEqual(self.client.post(reverse(f"workorders:{name}", args=[self.order.pk]), {"expected_version": 1}).status_code, 403)
        self.assertEqual(WorkOrder.objects.count(), 1)

    def test_filing_types_and_unknown_type(self):
        response = self.client.get(reverse("workorders:filing-types"))
        self.assertContains(response, "FAKE ALPHA")
        self.assertContains(response, "View forms")
        self.assertNotContains(response, "1701Q")
        for suffix in ("", "new/"):
            self.assertEqual(self.client.get(f"/filings/1701q/{suffix}").status_code, 404)

    def test_create_is_fixed_to_selected_filing_and_audited(self):
        data = self.post_data(client_name="FAKE BRAVO", rdo_code="53a", atc_code="pt010")
        data.update(form_code="1701Q", expected_form_number="OTHER", year_end_month="06", calendar_year=False,
                    status="SUBMITTED", approved_for_submission=True, created_by=self.approver.pk)
        response = self.client.post(reverse("workorders:filing-create", args=["2551q"]), data)
        self.assertEqual(response.status_code, 302)
        order = WorkOrder.objects.get(client_name="FAKE BRAVO")
        self.assertEqual(order.form_code, "2551Q")
        self.assertEqual(order.expected_form_number, "2551Qv2018")
        self.assertEqual(order.year_end_month, "12")
        self.assertTrue(order.calendar_year)
        self.assertEqual(order.status, "DRAFT")
        self.assertFalse(order.approved_for_submission)
        self.assertEqual(order.created_by, self.preparer)
        self.assertEqual(order.atc_code, "PT 010")
        self.assertEqual(order.rdo_code, "53A")
        self.assertEqual(order.tin4, "00000")
        self.assertEqual(order.audit_events.count(), 1)

    def test_administrator_can_create_without_becoming_superuser(self):
        self.client.force_login(self.administrator)
        response = self.client.post(reverse("workorders:create"), self.post_data(client_name="FAKE ADMIN ORDER"))
        self.assertEqual(response.status_code, 302)
        self.administrator.refresh_from_db()
        self.assertFalse(self.administrator.is_superuser)

    def test_invalid_create_redisplays_errors_and_preserves_values(self):
        for atc in ("PT 999", "", "-"):
            response = self.client.post(reverse("workorders:create"), self.post_data(atc_code=atc))
            self.assertEqual(response.status_code, 409)
            self.assertTrue(response.context["form"].errors)
        self.assertEqual(WorkOrder.objects.count(), 1)

    def test_atc_and_zero_confirmation_not_preselected(self):
        response = self.client.get(reverse("workorders:create"))
        form = response.context["form"]
        self.assertFalse(form["atc_code"].value())
        self.assertFalse(form["zero_filing_approved"].value())
        self.assertEqual(len(response.context["atcs"]), 22)

    def test_edit_updates_derived_name_and_history(self):
        data = self.post_data(client_name="FAKE ALPHA", filing_quarter=4)
        data["expected_version"] = self.order.version
        response = self.client.post(reverse("workorders:edit", args=[self.order.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.expected_return_period, "122026Q4")
        self.assertEqual(self.order.version, 2)
        self.assertEqual(self.order.audit_events.filter(kind="EDITED").count(), 1)

    def test_editing_ready_can_remove_zero_confirmation_and_returns_draft(self):
        order = create_work_order(actor=self.preparer, data=fake_data(zero_filing_approved=True))
        transition_work_order(work_order_id=order.pk, actor=self.preparer, expected_version=1, target="READY_TO_PREPARE")
        data = self.post_data(zero_filing_approved=False, expected_version=2)
        response = self.client.post(reverse("workorders:edit", args=[order.pk]), data)
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "DRAFT")
        self.assertFalse(order.zero_filing_approved)

    def test_stale_edit_rejected_without_overwriting(self):
        edit_work_order(work_order_id=self.order.pk, actor=self.preparer, expected_version=1, changes={"filing_quarter": 4})
        response = self.client.post(reverse("workorders:edit", args=[self.order.pk]), self.post_data(expected_version=1))
        self.assertContains(response, "Reload before saving")
        self.order.refresh_from_db()
        self.assertEqual(self.order.filing_quarter, 4)
        self.assertEqual(self.order.version, 2)

    def test_write_conflict_and_database_lock_show_recoverable_errors(self):
        url = reverse("workorders:edit", args=[self.order.pk])
        for error in (ValidationError("Reload the record."), OperationalError("database is locked")):
            with self.subTest(error=type(error).__name__), patch("workorders.views.services.edit_work_order", side_effect=error):
                response = self.client.post(url, self.post_data(expected_version=1))
                self.assertEqual(response.status_code, 409)
                self.assertContains(response, "review the highlighted fields", status_code=409)

    def test_ready_and_draft_are_post_only_and_version_checked(self):
        for name in ("ready", "draft"):
            self.assertEqual(self.client.get(reverse(f"workorders:{name}", args=[self.order.pk])).status_code, 405)
        ready_url = reverse("workorders:ready", args=[self.order.pk])
        self.assertEqual(self.client.post(ready_url, {}).status_code, 400)
        self.assertEqual(self.client.post(ready_url, {"expected_version": 1}).status_code, 409)
        edit_work_order(work_order_id=self.order.pk, actor=self.preparer, expected_version=1, changes={"zero_filing_approved": True})
        self.assertEqual(self.client.post(ready_url, {"expected_version": 1}).status_code, 409)
        self.assertEqual(self.client.post(ready_url, {"expected_version": 2}).status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "READY_TO_PREPARE")
        self.assertEqual(self.client.post(reverse("workorders:draft", args=[self.order.pk]), {"expected_version": 3}).status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "DRAFT")

    def test_all_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.preparer)
        for url in (reverse("workorders:create"), reverse("workorders:edit", args=[self.order.pk]),
                    reverse("workorders:ready", args=[self.order.pk]), reverse("workorders:draft", args=[self.order.pk])):
            self.assertEqual(client.post(url, self.post_data(expected_version=1)).status_code, 403)

    def test_combined_filters_and_invalid_filters(self):
        order = create_work_order(actor=self.preparer, data=fake_data(client_name="FAKE BRAVO", client_id="DEMO-B", filing_year="2025", filing_quarter=1, zero_filing_approved=True))
        transition_work_order(work_order_id=order.pk, actor=self.preparer, expected_version=1, target="READY_TO_PREPARE")
        url = reverse("workorders:list")
        response = self.client.get(url, {"client": "demo-b", "year": "2025", "quarter": "1", "status": "READY_TO_PREPARE"})
        self.assertEqual(list(response.context["page_obj"].object_list), [order])
        self.assertNotContains(response, "FAKE ALPHA")
        for bad in ({"year": "oops"}, {"quarter": "9"}, {"status": "SUBMITTED"}):
            response = self.client.get(url, bad)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["filter_form"].errors)
            self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_empty_state_and_pagination_preserve_filters(self):
        url = reverse("workorders:list")
        self.assertContains(self.client.get(url, {"client": "does-not-exist"}), "No matching work orders")
        for index in range(21):
            create_work_order(actor=self.preparer, data=fake_data(client_name=f"FAKE PAGE {index}"))
        response = self.client.get(url, {"client": "FAKE PAGE", "page": "2"})
        self.assertEqual(len(response.context["page_obj"].object_list), 1)
        self.assertEqual(response.context["filter_query"], "client=FAKE+PAGE")

    def test_history_requires_audit_permission_and_escapes_content(self):
        order = create_work_order(actor=self.preparer, data=fake_data(client_name='<script>alert("fake")</script>'))
        response = self.client.get(reverse("workorders:detail", args=[order.pk]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("fake")</script>')
        self.assertContains(response, "test_preparer")
        reader = get_user_model().objects.create_user(username="limited_reader")
        reader.user_permissions.add(Permission.objects.get(content_type__app_label="workorders", codename="view_workorder"))
        self.client.force_login(reader)
        response = self.client.get(reverse("workorders:detail", args=[order.pk]))
        self.assertContains(response, "does not have access to activity history")
        self.assertFalse(response.context["history"].object_list)

    def test_future_endpoints_remain_absent(self):
        for url in (f"/work-orders/{self.order.pk}/approve/", f"/work-orders/{self.order.pk}/pdf/", "/api/agent/next-preparation/", "/media/example.pdf"):
            self.assertEqual(self.client.get(url).status_code, 404)
