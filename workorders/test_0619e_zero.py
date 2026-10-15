from types import SimpleNamespace
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from .definitions.form_0619e import DEFINITION
from .models import FormDefinition
from automation_api.worker_services import allowed_pdf_page_counts, payload


class Definition0619ETests(SimpleTestCase):
    def test_identity_and_zero_only_rules(self):
        order = SimpleNamespace(filing_month=1, filing_year='2026', combined_tin='63984860500000')
        self.assertEqual(DEFINITION.return_period(order), '012026')
        self.assertEqual(DEFINITION.saved_return_name(order), '63984860500000-0619E-012026')
        self.assertEqual(DEFINITION.validate_data({}), {})
        DEFINITION.validate_zero(True)
        with self.assertRaises(ValidationError):
            DEFINITION.validate_data({'atc_code': 'WME10'})
        DEFINITION.validate_zero(False)
        with self.assertRaises(ValidationError):
            DEFINITION.validate_zero("false")
        self.assertEqual(allowed_pdf_page_counts(SimpleNamespace(current_snapshot=SimpleNamespace(
            data={'form': {'expected_form_number': '0619E'}}))), {1})


class Catalog0619ETests(TestCase):
    def test_new_form_stays_unavailable_until_parent_route_is_verified(self):
        form = FormDefinition.objects.get(definition_key='0619e_zero')
        self.assertEqual(form.automation_key, 'PREPARE_0619E_ZERO')
        self.assertFalse(form.preparation_automation_available)
        self.assertFalse(form.submission_automation_available)
        form.full_clean()
