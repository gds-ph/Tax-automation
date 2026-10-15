from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .test_support import make_profile
from .models import ExpandedWithholdingDraft, WorkOrder


class SupplierPreviewTests(TestCase):
    def test_summary_requires_review_before_queue(self):
        actor = get_user_model().objects.create_superuser('preview-test', password='test-only')
        profile = make_profile(actor, key='0619e_zero')
        draft = ExpandedWithholdingDraft.objects.create(client=profile.client, year=2025, month=7,
            rows=[dict(payee='SAMPLE SUPPLIER', tin='001-002-003-00000', atc='WC120',
                       base='100000.00', rate='2', tax='2000.00', reference='Sample')], total='2000.00')
        from .catalog_services import update_record
        form = profile.form_definition
        update_record(model=type(form), pk=form.pk, actor=actor, expected_version=form.version, changes={'preparation_automation_available': True})
        self.client.force_login(actor)
        url = reverse('workorders:supplier-prepare', args=[profile.client_id, draft.pk])
        response = self.client.get(url)
        self.assertContains(response, '2000.00')
        self.assertContains(response, 'Review before preparation')
        self.assertContains(response, 'Queue preparation')
        self.assertEqual(self.client.post(url, {'action': 'queue', 'reviewed': 'on'}).status_code, 400)
        self.assertFalse(WorkOrder.objects.exists())
        other = make_profile(actor, key='0619e_zero')
        self.assertEqual(self.client.get(reverse('workorders:supplier-prepare', args=[other.client_id, draft.pk])).status_code, 404)
