from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from workorders.services import edit_work_order
from workorders.test_support import legacy_test_fixture_order as create_work_order
from workorders.test_support import fake_data
from .models import AuditEvent


class AuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="audit_admin", password="test-only-password")

    def test_append_only(self):
        order = create_work_order(actor=self.actor, data=fake_data())
        event = order.audit_events.get()
        for operation in (lambda: event.save(), lambda: event.delete(),
                          lambda: AuditEvent.objects.filter(pk=event.pk).update(kind="APPROVED"),
                          lambda: AuditEvent.objects.all().delete(),
                          lambda: AuditEvent.objects.bulk_update([event], ["kind"])):
            with self.assertRaises(ValidationError):
                operation()
        self.assertEqual(AuditEvent.objects.get(pk=event.pk).kind, "CREATED")

    def test_existing_id_cannot_be_overwritten(self):
        order = create_work_order(actor=self.actor, data=fake_data())
        event = order.audit_events.get()
        clone = AuditEvent(id=event.pk, work_order=order, actor=self.actor, kind="EDITED")
        with self.assertRaises(ValidationError):
            clone.save()

    def test_field_names_logged_without_taxpayer_values(self):
        order = create_work_order(actor=self.actor, data=fake_data())
        edit_work_order(work_order_id=order.pk, actor=self.actor, expected_version=1,
                        changes={"filing_quarter": 4})
        event = order.audit_events.get(kind="EDITED")
        self.assertEqual(event.changed_fields, ["filing_quarter"])
        self.assertNotIn("CHANGED FAKE ADDRESS", str(list(order.audit_events.values())))

    def test_event_requires_subject_and_field_name_list(self):
        with self.assertRaises(ValidationError):
            AuditEvent.objects.create(actor=self.actor, kind="CREATED")
        order = create_work_order(actor=self.actor, data=fake_data())
        with self.assertRaises(ValidationError):
            AuditEvent.objects.create(actor=self.actor, work_order=order, kind="EDITED", changed_fields={"secret": "bad"})

    def test_admin_read_only(self):
        order = create_work_order(actor=self.actor, data=fake_data())
        event = order.audit_events.get()
        self.client.force_login(self.actor)
        url = reverse("admin:audit_auditevent_change", args=[event.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"kind": "APPROVED"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:audit_auditevent_add")).status_code, 403)
