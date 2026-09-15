from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, Client as BrowserClient, override_settings
from django.urls import reverse
from workorders.models import WorkOrder, WorkOrderSnapshot, ClientFilingProfile, FormDefinition
from workorders.test_support import make_profile
from workorders.catalog_services import update_record, create_record


@override_settings(CLIENT_FILES_URL='')
class ClientNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor=get_user_model().objects.create_superuser(username='fake_ui_admin',password='fake-only-password')
        cls.profile=make_profile(cls.actor,client_data={'trade_name':'FAKE CLIENT ONE'})
        cls.other=make_profile(cls.actor,client_data={'trade_name':'FAKE CLIENT TWO'})
        cls.planned=create_record(model=ClientFilingProfile,actor=cls.actor,data={'client':cls.profile.client,'form_definition':FormDefinition.objects.get(definition_key='planned_1701q')})

    def setUp(self):
        self.client.force_login(self.actor)
        self.url=reverse('workorders:client-prepare',args=[self.profile.client_id,self.profile.pk])

    def post_data(self):
        response=self.client.get(self.url)
        return dict(request_token=response.context['form']['request_token'].value(),filing_year='2026',filing_quarter='3',atc_code='pt010',zero_filing_approved='on')

    def test_home_and_sidebar_start_with_clients(self):
        response=self.client.get('/')
        self.assertContains(response,'FAKE CLIENT ONE')
        self.assertContains(response,'Clients')
        self.assertNotContains(response,'Choose a filing type')
        self.assertIn('no-store',response.headers['Cache-Control'])

    def test_client_search_and_empty_state(self):
        response=self.client.get(reverse('workorders:clients'),{'q':'CLIENT ONE'})
        self.assertContains(response,'FAKE CLIENT ONE');self.assertNotContains(response,'FAKE CLIENT TWO')
        self.assertContains(self.client.get(reverse('workorders:clients'),{'q':'NOT FOUND'}),'No matching clients')

    def test_only_configured_active_profiles_shown(self):
        response=self.client.get(reverse('workorders:client-detail',args=[self.profile.client_id]))
        self.assertContains(response,'Prepare 2551Q');self.assertContains(response,'Not yet automated')
        self.assertNotContains(response,str(self.other.pk))
        update_record(model=ClientFilingProfile,pk=self.profile.pk,actor=self.actor,expected_version=1,changes={'is_active':False})
        response=self.client.get(reverse('workorders:client-detail',args=[self.profile.client_id]))
        self.assertNotContains(response,'Prepare 2551Q')

    def test_preparation_get_has_no_side_effects(self):
        response=self.client.get(self.url)
        self.assertContains(response,'Queue preparation')
        self.assertContains(response,'This queues preparation for the VM worker')
        self.assertEqual(WorkOrder.objects.count(),0)
        self.assertFalse(response.context['form']['zero_filing_approved'].value())
        self.assertNotIn('atc_code', response.context['form'].fields)

    def test_current_period_defaults_across_quarter_and_year_boundaries(self):
        from datetime import date
        for day, quarter in ((date(2026, 3, 31), 1), (date(2026, 4, 1), 2),
                             (date(2026, 9, 15), 3), (date(2026, 10, 1), 4),
                             (date(2027, 1, 1), 1)):
            with self.subTest(day=day), patch('workorders.client_views.timezone.localdate', return_value=day):
                form = self.client.get(self.url).context['form']
                self.assertEqual(form['filing_year'].value(), str(day.year))
                self.assertEqual(form['filing_quarter'].value(), quarter)

    def test_prepare_creates_and_queues_atomically(self):
        data=self.post_data();data.update(client_filing_profile=str(self.other.pk),status='SUBMITTED',form_code='1701Q')
        response=self.client.post(self.url,data)
        self.assertEqual(response.status_code,302)
        order=WorkOrder.objects.get()
        self.assertEqual(order.client_id,self.profile.client_id)
        self.assertEqual(order.client_filing_profile_id,self.profile.pk)
        self.assertEqual(order.status,'READY_TO_PREPARE')
        self.assertEqual(order.atc_code,'PT 010')
        self.assertEqual(order.automation_key,'PREPARE_2551QV2018_ZERO')
        self.assertEqual(order.audit_events.count(),2)
        self.assertEqual(order.snapshots.count(),1)
        self.assertContains(self.client.get(response.url),'Waiting for the VM worker')

    def test_repeated_post_does_not_duplicate_or_requeue(self):
        data=self.post_data()
        one=self.client.post(self.url,data);two=self.client.post(self.url,data)
        self.assertEqual(one.url,two.url)
        self.assertEqual(WorkOrder.objects.count(),1)
        self.assertEqual(WorkOrder.objects.get().audit_events.count(),2)

    def test_queue_failure_rolls_back_draft_and_snapshot(self):
        from django.core.exceptions import ValidationError
        data=self.post_data()
        with patch('workorders.services.transition_work_order',side_effect=ValidationError('Cannot prepare')):
            self.assertEqual(self.client.post(self.url,data).status_code,409)
        self.assertEqual(WorkOrder.objects.count(),0);self.assertEqual(WorkOrderSnapshot.objects.count(),0)

    def test_invalid_atc_and_zero_confirmation_do_not_create_orders(self):
        for field,value in (('zero_filing_approved',''),('filing_quarter','5')):
            data=self.post_data();data[field]=value
            response=self.client.post(self.url,data)
            self.assertIn(response.status_code,(200,409))
            self.assertTrue(response.context['form'].errors)
        self.assertEqual(WorkOrder.objects.count(),0)

    def test_wrong_client_profile_and_planned_form_cannot_execute(self):
        wrong=reverse('workorders:client-prepare',args=[self.other.client_id,self.profile.pk])
        self.assertEqual(self.client.get(wrong).status_code,404)
        planned=reverse('workorders:client-prepare',args=[self.planned.client_id,self.planned.pk])
        self.assertEqual(self.client.get(planned).status_code,409)
        self.assertEqual(self.client.post(planned,self.post_data()).status_code,409)
        self.assertEqual(WorkOrder.objects.count(),0)

    def test_signed_token_cannot_switch_profiles(self):
        data=self.post_data()
        other=reverse('workorders:client-prepare',args=[self.other.client_id,self.other.pk])
        self.assertEqual(self.client.post(other,data).status_code,409)
        data['request_token']='tampered'
        self.assertEqual(self.client.post(self.url,data).status_code,400)
        self.assertEqual(WorkOrder.objects.count(),0)

    def test_stale_configuration_requires_new_review(self):
        data=self.post_data()
        update_record(model=ClientFilingProfile,pk=self.profile.pk,actor=self.actor,expected_version=1,changes={'default_atc_code':'PT 040'})
        self.assertEqual(self.client.post(self.url,data).status_code,409)
        self.assertEqual(WorkOrder.objects.count(),0)

    def test_login_permissions_and_csrf(self):
        self.client.logout()
        for url in ('/',reverse('workorders:clients'),reverse('workorders:client-detail',args=[self.profile.client_id]),self.url):
            self.assertEqual(self.client.get(url).status_code,302)
        approver=get_user_model().objects.create_user(username='fake_approver')
        approver.groups.add(Group.objects.get(name='Approver'))
        self.client.force_login(approver)
        detail=self.client.get(reverse('workorders:client-detail',args=[self.profile.client_id]))
        self.assertEqual(detail.status_code,200);self.assertNotContains(detail,'Prepare 2551Q')
        self.assertEqual(self.client.get(self.url).status_code,403)
        csrf=BrowserClient(enforce_csrf_checks=True);csrf.force_login(self.actor)
        self.assertEqual(csrf.post(self.url,{}).status_code,403)
