import hashlib
import uuid
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings, Client as Browser
from django.urls import reverse
from .cor_forms import CORReviewForm
from .cor_services import save_setup
from .models import Client, ClientFilingProfile, RegistrationSetup, WorkOrder
from .test_support import fake_client_data


@override_settings(CLIENT_FILES_URL='')
class CORSetupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.actor = get_user_model().objects.create_superuser(username='cor-admin', password='test-only')
        self.client.force_login(self.actor)
        self.pdf = b'%PDF-synthetic'
        self.draft = {'actor': self.actor.pk, 'folder': 'FAKE OFFICE', 'path': 'FAKE OFFICE/PERMANENT/COR.pdf',
                      'sha256': hashlib.sha256(self.pdf).hexdigest(), 'transcript': 'FAKE COR',
                      'initial': {}, 'rows': [], 'warnings': [], 'model': 'fake-model'}
        self.draft_id = uuid.uuid4()
        cache.set('cor-review:' + str(self.draft_id), self.draft, 3600)
        self.url = reverse('workorders:cor-review', args=[self.draft_id])
        self.data = fake_client_data() | {'filings': ['2550Q', '1701Q'], 'confirmed': True,
                                        'calendar_or_fiscal': 'CALENDAR', 'year_end_month': '12'}

    def test_review_get_has_no_mutation(self):
        self.assertContains(self.client.get(self.url), 'Save filing setup')
        self.assertEqual(Client.objects.count(), 0)

    @patch('workorders.cor_views.read_cor')
    @patch('workorders.cor_views.source_document')
    def test_automatic_cards_reuse_scan_without_creating_filing(self, source, reader):
        source.return_value = self.pdf
        reader.return_value = self.draft | {'initial': {'filings': ['1701Q']},
            'rows': [{'form_code': '1701Q', 'tax_type': 'Income tax', 'frequency': 'QUARTERLY', 'uncertain': False}]}
        token = signing.dumps({'actor': self.actor.pk, 'client': self.draft['folder'],
                               'path': self.draft['path']}, salt='registration-file')
        for _ in range(2):
            response = self.client.post(reverse('workorders:cor-read'), {'token': token, 'cards': '1'})
            self.assertContains(response, 'Quarterly Income Tax Return')
            self.assertContains(response, 'data-cor-digest')
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(WorkOrder.objects.count(), 0)
        self.assertEqual(Client.objects.count(), 0)

    @patch('workorders.cor_views.source_document')
    def test_cor_can_save_without_contact_details(self, source):
        source.return_value = self.pdf
        response = self.client.post(self.url, self.data | {'telephone_number': '', 'email_address': ''})
        self.assertEqual(response.status_code, 302)
        client = Client.objects.get()
        self.assertEqual(client.telephone_number, '')
        self.assertEqual(client.email_address, '')
        self.assertEqual(WorkOrder.objects.count(), 0)

    @patch('workorders.cor_views.source_document')
    def test_confirmed_save_creates_audited_cards_and_link_no_job(self, source):
        source.return_value = self.pdf
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(RegistrationSetup.objects.count(), 1)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(ClientFilingProfile.objects.count(), 2)
        self.assertEqual(WorkOrder.objects.count(), 0)
        self.assertFalse(ClientFilingProfile.objects.filter(form_definition__preparation_automation_available=True).exists())
        self.assertEqual(Client.objects.get().audit_events.count(), 1)
        # Replaying a saved review returns the existing client, never duplicates it.
        self.assertEqual(self.client.post(self.url, self.data).url, response.url)
        self.assertEqual(Client.objects.count(), 1)
        page = self.client.get(response.url)
        self.assertContains(page, 'Quarterly Value-Added Tax Return')
        self.assertNotContains(page, 'Prepare 2551Q')

    @patch('workorders.cor_views.source_document')
    def test_changed_source_prevents_save(self, source):
        source.return_value = b'%PDF-changed'
        self.assertContains(self.client.post(self.url, self.data), 'source PDF changed')
        self.assertFalse(Client.objects.exists())

    def test_confirmation_and_ambiguous_forms_rejected(self):
        for changes in ({'confirmed': ''}, {'filings': ['2550Q', '2551Q']},
                        {'filings': ['1701', '1701A']}, {'filings': ['0605']},
                        {'tin4': '001'}, {'calendar_or_fiscal': 'CALENDAR', 'year_end_month': '06'}):
            with self.subTest(changes=changes):
                self.assertFalse(CORReviewForm(self.data | changes).is_valid())

    def test_unauthorized_and_other_actor_cannot_read_draft(self):
        user = get_user_model().objects.create_user(username='no-config')
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        other = get_user_model().objects.create_superuser(username='other-admin')
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url).status_code, 410)

    def test_expired_review_and_csrf(self):
        browser = Browser(enforce_csrf_checks=True)
        browser.force_login(self.actor)
        self.assertEqual(browser.post(self.url, self.data).status_code, 403)
        cache.clear()
        self.assertEqual(self.client.get(self.url).status_code, 410)

    @patch('workorders.cor_views.read_cor')
    @patch('workorders.cor_views.source_document')
    def test_read_only_accepts_signed_document_and_creates_review(self, source, reader):
        source.return_value = self.pdf
        reader.return_value = {k: self.draft[k] for k in ('initial', 'rows', 'warnings', 'transcript', 'model')}
        url = reverse('workorders:cor-read')
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {'token': 'tampered'}).status_code, 404)
        reader.assert_not_called()
        token = signing.dumps({'actor': self.actor.pk, 'client': self.draft['folder'], 'path': self.draft['path']}, salt='registration-file')
        response = self.client.post(url, {'token': token})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(response.url), 'Save filing setup')
        self.assertFalse(Client.objects.exists())

    @patch('workorders.client_directory.names', return_value=['FAKE OFFICE'])
    def test_saved_directory_becomes_one_searchable_client(self, names):
        form = CORReviewForm(self.data)
        self.assertTrue(form.is_valid(), form.errors)
        save_setup(actor=self.actor, draft=self.draft, cleaned=form.cleaned_data)
        page = self.client.get(reverse('workorders:clients'), {'q': 'FAKE OFFICE'})
        self.assertEqual(page.context['page_obj'].paginator.count, 1)
        self.assertContains(page, 'View forms')

    def test_duplicate_tin_rollback(self):
        from django.core.exceptions import ValidationError
        form = CORReviewForm(self.data); self.assertTrue(form.is_valid())
        save_setup(actor=self.actor, draft=self.draft, cleaned=form.cleaned_data)
        with self.assertRaises(ValidationError):
            save_setup(actor=self.actor, draft=self.draft | {'folder': 'ANOTHER FAKE OFFICE'}, cleaned=form.cleaned_data)
        self.assertEqual(Client.objects.count(), 1)
