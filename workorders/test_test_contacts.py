from django.test import TestCase
from django.contrib.auth import get_user_model
from .test_support import fake_client_data
from .models import Client
from .catalog_services import create_record, update_record
from .contact_defaults import TEST_CLIENT_CODES, TEST_CONTACT, COMPANY_CONTACT
from .forms import ClientForm

class TestClientContactTests(TestCase):
    def test_test_contacts_survive_edits_and_render(self):
        actor=get_user_model().objects.create_superuser('contact_test')
        for code in TEST_CLIENT_CODES:
            c=create_record(model=Client,actor=actor,data=fake_client_data(client_code=code))
            c=update_record(model=Client,pk=c.pk,actor=actor,expected_version=c.version,changes={'trade_name':'Test renamed'})
            for field,value in TEST_CONTACT.items():
                self.assertEqual(getattr(c,field),value)
                self.assertEqual(ClientForm(instance=c).initial[field],value)
        c=create_record(model=Client,actor=actor,data=fake_client_data(client_code='REGULAR-CLIENT'))
        self.assertEqual(c.email_address,COMPANY_CONTACT['email_address'])
