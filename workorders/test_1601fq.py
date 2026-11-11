from types import SimpleNamespace
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from .definitions.form_1601fq import DEFINITION
from .models import FormDefinition
from .definitions import validate_period
from .cor_extraction import FORM_CATALOG
from .cor_services import FORM_KEYS


class Definition1601FQTests(SimpleTestCase):
    def test_quarterly_identity_and_strict_zero_contract(self):
        for quarter in (1, 2, 3, 4):
            order = SimpleNamespace(filing_year='2026', filing_quarter=quarter, combined_tin='00100200300000')
            self.assertEqual(DEFINITION.return_period(order), f'2026Q{quarter}')
            self.assertEqual(DEFINITION.saved_return_name(order), f'00100200300000-1601FQ-2026Q{quarter}')
        DEFINITION.validate_zero(True)
        for value in (False, 1, 'true', None):
            with self.assertRaises(ValidationError):
                DEFINITION.validate_zero(value)
        self.assertEqual(DEFINITION.validate_data({}, require_atc=True), {})
        with self.assertRaises(ValidationError):
            DEFINITION.validate_data({'atc_code': 'WMF10'})
        with self.assertRaises(ValidationError):
            DEFINITION.validate_profile(SimpleNamespace(calendar_or_fiscal='FISCAL', year_end_month='06'))
        with self.assertRaises(ValidationError):
            validate_period('QUARTERLY', '2026', 10, None)


class Catalog1601FQTests(TestCase):
    def test_catalog_and_registration_keep_unverified_route_disabled(self):
        form = FormDefinition.objects.get(definition_key='1601fq_zero')
        form.full_clean()
        self.assertEqual(form.filing_frequency, 'QUARTERLY')
        self.assertEqual(FORM_KEYS['1601FQ'], form.definition_key)
        self.assertEqual(FORM_CATALOG['1601FQ'][1], 'QUARTERLY')
        self.assertFalse(form.preparation_automation_available)
        self.assertFalse(form.submission_automation_available)

    def test_unverified_profile_cannot_queue(self):
        from django.contrib.auth import get_user_model
        from .test_support import make_profile
        from .client_views import available, PreparationForm
        from .services import create_work_order, transition_work_order
        actor = get_user_model().objects.create_superuser('fq-gate', password='test-only')
        profile = make_profile(actor, key='1601fq_zero')
        self.assertFalse(available(profile))
        form = PreparationForm(form_code='1601FQ', can_auto_approve=True)
        self.assertNotIn('auto_approve', form.fields)
        self.assertNotIn('filing_month', form.fields)
        self.assertEqual(form.fields['filing_mode'].choices, [('ZERO', 'Zero filing')])
        with self.assertRaises(ValidationError):
            order = create_work_order(actor=actor, client_filing_profile_id=profile.pk,
                                      data=dict(filing_year='2026', filing_quarter=3,
                                                zero_filing=True, zero_filing_approved=True, form_data={}))
            transition_work_order(work_order_id=order.pk, actor=actor,
                                  expected_version=order.version, target='READY_TO_PREPARE')
