from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model
from .period_policy import validate_completed_period, default_completed_period, manila_today
from .client_views import PreparationForm
from .test_support import make_profile, order_data
from .services import create_work_order, transition_work_order
from .models import WorkOrder


class PeriodPolicyTests(SimpleTestCase):
    def test_boundaries_and_leap_year(self):
        for frequency, year, month, quarter, end, next_day in [
            ('MONTHLY', '2024', 2, None, date(2024,2,29), date(2024,3,1)),
            ('QUARTERLY', '2026', None, 4, date(2026,12,31), date(2027,1,1))]:
            with self.assertRaises(ValidationError):
                validate_completed_period(frequency,year,month,quarter,today=end)
            validate_completed_period(frequency,year,month,quarter,today=next_day)

    def test_defaults_and_future_year(self):
        self.assertEqual(default_completed_period('QUARTERLY',today=date(2026,10,10))['filing_quarter'],3)
        self.assertEqual(default_completed_period('MONTHLY',today=date(2026,10,10))['filing_month'],9)
        for freq in ('MONTHLY','QUARTERLY'):
            self.assertEqual(default_completed_period(freq,today=date(2026,1,1))['filing_year'],'2025')
        with self.assertRaises(ValidationError):
            validate_completed_period('QUARTERLY','2027',quarter=1,today=date(2026,10,10))

    def test_manila_day_boundary(self):
        with patch('django.utils.timezone.now',return_value=datetime(2026,9,30,16,0,tzinfo=dt_timezone.utc)):
            self.assertEqual(manila_today(),date(2026,10,1))

    @patch('workorders.period_policy.manila_today',return_value=date(2026,10,10))
    def test_browser_form_flags_quarter(self, _today):
        form=PreparationForm(data=dict(filing_mode='ZERO',filing_year='2026',filing_quarter=4,
            zero_filing_approved=True,request_token='fake'),frequency='QUARTERLY')
        self.assertFalse(form.is_valid())
        self.assertIn('Advance filing',str(form.errors['filing_quarter']))


class QueuePeriodTests(TestCase):
    @patch('workorders.period_policy.manila_today',return_value=date(2026,10,10))
    def test_service_rejects_future_period_across_automated_definitions(self, _today):
        from .definitions import DEFINITIONS
        actor=get_user_model().objects.create_superuser(username='period-test',password='test-only')
        for key, definition in DEFINITIONS.items():
            with self.subTest(key=key):
                profile=make_profile(actor,key=key)
                from .catalog_services import update_record
                from .models import FormDefinition
                form=profile.form_definition
                if not form.preparation_automation_available:
                    update_record(model=FormDefinition,pk=form.pk,actor=actor,expected_version=form.version,changes={'preparation_automation_available':True})
                data=order_data(zero_filing_approved=True,form_data={'atc_code':'PT 010'} if key=='2551qv2018_zero' else {})
                if definition.filing_frequency=='MONTHLY':
                    data.update(filing_month=10,filing_quarter=None)
                else:
                    data.update(filing_quarter=4)
                order=create_work_order(actor=actor,client_filing_profile_id=profile.pk,data=data)
                with self.assertRaisesMessage(ValidationError, 'Advance filing'):
                    transition_work_order(work_order_id=order.pk,actor=actor,expected_version=order.version,target='READY_TO_PREPARE')
                order.refresh_from_db()
                self.assertEqual(order.status,'DRAFT')
