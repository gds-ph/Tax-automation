from io import BytesIO
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader
from .sample_form import AMOUNTS
from .models import WorkOrder


class SampleFormTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='sample-user')
        self.user.groups.add(Group.objects.get(name='Preparer'))
        self.client.force_login(self.user)
        self.url = reverse('workorders:sample-form')

    def test_pdf_is_draft_and_does_not_create_work_order(self):
        data = dict(month='5', year='2026', amended='No', withheld='No', sheets=0, atc='WW010',
                    tin='000-000-000-00000', rdo='047', name='SAMPLE ONLY', address='Sample address',
                    zip='1200', phone='0272554774', category='Private', email='example@example.invalid', relief='No')
        data.update({f'amount_{n}': '0.00' for n in AMOUNTS})
        response = self.client.post(self.url, data)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['X-Frame-Options'], 'SAMEORIGIN')
        pdf = PdfReader(BytesIO(response.content))
        self.assertEqual(len(pdf.pages), 1)
        self.assertIn('SAMPLE ONLY', pdf.pages[0].extract_text())
        self.assertIn('NOT FOR FILING', pdf.pages[0].extract_text())
        self.assertEqual(WorkOrder.objects.count(), 0)
        data['year'] = 'bad'
        self.assertEqual(self.client.post(self.url, data).status_code, 400)

    def test_get_and_permission(self):
        self.assertContains(self.client.get(self.url), 'Preview PDF')
        self.assertEqual(self.client.get(self.url, {'client': 'bad-id'}).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
