from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, Client as BrowserClient, override_settings
from django.urls import reverse
from workorders.models import WorkOrder, WorkOrderSnapshot, ClientFilingProfile, FormDefinition
from workorders.test_support import make_profile, order_data
from workorders.services import create_work_order
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
        return dict(filing_mode='ZERO',request_token=response.context['form']['request_token'].value(),filing_year='2026',filing_quarter='3',atc_code='pt010',zero_filing_approved='on')

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

    def test_client_tabs_select_sections_from_the_url(self):
        detail=reverse('workorders:client-detail',args=[self.profile.client_id])
        cards=self.client.get(detail)
        self.assertContains(cards,'Prepare 2551Q');self.assertNotContains(cards,'Registered details')
        details=self.client.get(detail,{'tab':'details'})
        self.assertContains(details,'Registered details');self.assertContains(details,'FAKE ADDRESS')
        self.assertNotContains(details,'Prepare 2551Q')
        history=self.client.get(detail,{'tab':'history'})
        self.assertContains(history,'Filing history');self.assertNotContains(history,'Prepare 2551Q')

    def test_unknown_tab_falls_back_and_keeps_other_parameters(self):
        detail=reverse('workorders:client-detail',args=[self.profile.client_id])
        self.assertContains(self.client.get(detail,{'tab':'../etc'}),'Prepare 2551Q')
        response=self.client.get(detail,{'tab':'details','q':'keep-me'})
        self.assertContains(response,'q=keep-me')

    def test_saving_a_company_is_private_and_survives_a_directory_outage(self):
        from workorders.models import SavedCompany
        taxpayer=self.profile.client
        saved=reverse('workorders:saved-toggle')
        clients=reverse('workorders:clients')
        # No saved companies yet: the list opens on every client.
        self.assertContains(self.client.get(clients),'FAKE CLIENT TWO')
        self.client.post(saved,{'client':str(taxpayer.pk)})
        self.assertEqual(SavedCompany.objects.filter(user=self.actor,client=taxpayer).count(),1)
        page=self.client.get(clients)
        self.assertContains(page,'FAKE CLIENT ONE');self.assertNotContains(page,'FAKE CLIENT TWO')
        self.assertContains(self.client.get(clients,{'tab':'all'}),'FAKE CLIENT TWO')
        # Another user's list is unaffected, and they can still open the company.
        other=get_user_model().objects.create_superuser(username='fake_other_preparer')
        browser=BrowserClient();browser.force_login(other)
        self.assertNotContains(browser.get(clients,{'tab':'saved'}),'FAKE CLIENT ONE')
        self.assertEqual(browser.get(reverse('workorders:client-detail',args=[taxpayer.pk])).status_code,200)
        # Posting again unsaves it.
        self.client.post(saved,{'client':str(taxpayer.pk)})
        self.assertFalse(SavedCompany.objects.filter(user=self.actor).exists())

    def test_saved_folder_resolves_to_its_client_once_reviewed(self):
        from workorders.models import RegistrationSetup, SavedCompany
        taxpayer=self.profile.client
        SavedCompany.objects.create(user=self.actor,folder='FAKE FOLDER')
        RegistrationSetup.objects.create(folder='FAKE FOLDER',client=taxpayer,source_path='FAKE FOLDER/COR.pdf',
            source_sha256='0'*64,source_text='fake',reviewed_forms=['2551Q'],reviewed_by=self.actor)
        page=self.client.get(reverse('workorders:clients'),{'tab':'saved'})
        self.assertContains(page,'FAKE CLIENT ONE')

    def test_saved_toggle_requires_post_and_one_target(self):
        saved=reverse('workorders:saved-toggle')
        self.assertEqual(self.client.get(saved).status_code,405)
        self.assertEqual(self.client.post(saved,{}).status_code,404)
        self.assertEqual(self.client.post(saved,{'client':str(self.profile.client_id),'folder':'BOTH'}).status_code,404)
        csrf=BrowserClient(enforce_csrf_checks=True);csrf.force_login(self.actor)
        self.assertEqual(csrf.post(saved,{'folder':'FAKE'}).status_code,403)

    def edit_data(self, **changes):
        taxpayer = self.profile.client
        data = {name: getattr(taxpayer, name) for name in (
            'registered_name', 'trade_name', 'client_type', 'tin1', 'tin2', 'tin3', 'tin4', 'rdo_code',
            'registered_address', 'zip_code', 'telephone_number', 'email_address', 'line_of_business', 'client_code')}
        data.update(expected_version=taxpayer.version, is_active='on')
        data.update(changes)
        return data

    def test_client_edit_saves_audited_change_and_keeps_prepared_snapshots(self):
        taxpayer=self.profile.client
        order=create_work_order(actor=self.actor,client_filing_profile_id=self.profile.pk,data=order_data())
        url=reverse('workorders:client-edit',args=[taxpayer.pk])
        self.assertContains(self.client.get(url),'Edit company details')
        response=self.client.post(url,self.edit_data(registered_address='NEW ADDRESS ONLY'))
        self.assertRedirects(response,reverse('workorders:client-detail',args=[taxpayer.pk])+'?tab=details')
        taxpayer.refresh_from_db();order.refresh_from_db()
        self.assertEqual(taxpayer.registered_address,'NEW ADDRESS ONLY')
        self.assertEqual(taxpayer.version,2)
        # The prepared filing keeps the address it was reviewed with.
        self.assertEqual(order.registered_address,'FAKE ADDRESS')
        self.assertEqual(order.current_snapshot.data['client']['registered_address'],'FAKE ADDRESS')

    def test_edit_adds_selected_cards_and_preserves_existing(self):
        taxpayer = self.profile.client
        url = reverse('workorders:client-edit', args=[taxpayer.pk])
        self.assertContains(self.client.get(url), 'Already added')
        definition = FormDefinition.objects.filter(is_active=True).exclude(
            pk__in=taxpayer.filing_profiles.values('form_definition_id')).first()
        before = set(taxpayer.filing_profiles.values_list('pk', flat=True))
        response = self.client.post(url, self.edit_data(**{
            'cards-filings': [str(definition.pk)], 'cards-calendar_or_fiscal': 'FISCAL',
            'cards-year_end_month': '06'}))
        self.assertEqual(response.status_code, 302)
        profile = taxpayer.filing_profiles.get(form_definition=definition)
        self.assertEqual(profile.calendar_or_fiscal, 'FISCAL')
        self.assertEqual(profile.year_end_month, '06')
        self.assertTrue(before.issubset(set(taxpayer.filing_profiles.values_list('pk', flat=True))))
        self.assertTrue(profile.audit_events.filter(kind='CONFIG_CREATED').exists())
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_invalid_card_settings_do_not_save_client(self):
        taxpayer = self.profile.client
        definition = FormDefinition.objects.filter(is_active=True).exclude(
            pk__in=taxpayer.filing_profiles.values('form_definition_id')).first()
        response = self.client.post(reverse('workorders:client-edit', args=[taxpayer.pk]),
            self.edit_data(registered_name='SHOULD NOT SAVE', **{
                'cards-filings': [str(definition.pk)], 'cards-calendar_or_fiscal': 'CALENDAR',
                'cards-year_end_month': '06'}))
        self.assertContains(response, 'Calendar years end in December')
        taxpayer.refresh_from_db()
        self.assertNotEqual(taxpayer.registered_name, 'SHOULD NOT SAVE')
        self.assertFalse(taxpayer.filing_profiles.filter(form_definition=definition).exists())

    def test_existing_card_cannot_be_added_twice(self):
        response = self.client.post(reverse('workorders:client-edit', args=[self.profile.client_id]),
            self.edit_data(**{'cards-filings': [str(self.profile.form_definition_id)],
                             'cards-calendar_or_fiscal': 'CALENDAR', 'cards-year_end_month': '12'}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['cards'].errors)
        self.assertEqual(ClientFilingProfile.objects.filter(client=self.profile.client,
                         form_definition=self.profile.form_definition).count(), 1)

    def test_adding_cards_requires_profile_permission(self):
        from django.contrib.auth.models import Permission
        user = get_user_model().objects.create_user('details_only_editor')
        user.user_permissions.add(*Permission.objects.filter(codename__in=['view_client', 'change_client']))
        self.client.force_login(user)
        definition = FormDefinition.objects.filter(is_active=True).exclude(
            pk__in=self.profile.client.filing_profiles.values('form_definition_id')).first()
        response = self.client.post(reverse('workorders:client-edit', args=[self.profile.client_id]),
            self.edit_data(**{'cards-filings': [str(definition.pk)]}))
        self.assertEqual(response.status_code, 403)

    def test_rdo_email_is_optional_validated_and_separate_from_filing_email(self):
        from workorders.contact_defaults import COMPANY_CONTACT
        taxpayer = self.profile.client
        url = reverse('workorders:client-edit', args=[taxpayer.pk])
        invalid = self.client.post(url, self.edit_data(rdo_email='invalid'))
        self.assertContains(invalid, 'Enter a valid email address')
        response = self.client.post(url, self.edit_data(rdo_email='rdo@example.com'))
        self.assertEqual(response.status_code, 302)
        taxpayer.refresh_from_db()
        self.assertEqual(taxpayer.rdo_email, 'rdo@example.com')
        self.assertEqual(taxpayer.email_address, COMPANY_CONTACT['email_address'])
        detail = reverse('workorders:client-detail', args=[taxpayer.pk])
        self.assertContains(self.client.get(detail, {'tab': 'details'}), 'rdo@example.com')
        cleared = self.client.post(url, self.edit_data(rdo_email=''))
        self.assertEqual(cleared.status_code, 302)
        taxpayer.refresh_from_db()
        self.assertEqual(taxpayer.rdo_email, '')

    def test_client_edit_refuses_stale_version_and_duplicate_tin(self):
        taxpayer=self.profile.client
        url=reverse('workorders:client-edit',args=[taxpayer.pk])
        stale=self.client.post(url,self.edit_data(expected_version=99,registered_name='STALE'))
        self.assertContains(stale,'Reload before saving',status_code=200)
        # The shared fixture TIN must not block an unrelated edit; only a real change collides.
        distinct=make_profile(self.actor,client_data={'tin1':'111','tin2':'222','tin3':'333','tin4':'00001'}).client
        clash=self.client.post(url,self.edit_data(tin1=distinct.tin1,tin2=distinct.tin2,tin3=distinct.tin3,tin4=distinct.tin4))
        self.assertContains(clash,'Another client already uses this TIN')
        taxpayer.refresh_from_db()
        self.assertEqual(taxpayer.version,1)

    def test_client_edit_requires_change_permission(self):
        self.client.logout()
        viewer=get_user_model().objects.create_user(username='fake_viewer')
        viewer.groups.add(Group.objects.get(name='Approver'))
        self.client.force_login(viewer)
        url=reverse('workorders:client-edit',args=[self.profile.client_id])
        self.assertEqual(self.client.get(url).status_code,403)
        detail=self.client.get(reverse('workorders:client-detail',args=[self.profile.client_id]),{'tab':'details'})
        self.assertNotContains(detail,'Edit details')

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

class FilingModeTests(TestCase):
    def test_nonzero_and_missing_mode_cannot_be_queued_as_zero(self):
        from .client_views import PreparationForm
        for mode in ('NONZERO', ''):
            form = PreparationForm({'filing_mode': mode, 'filing_year': '2026',
                'filing_quarter': '2', 'zero_filing_approved': 'on', 'request_token': 'test'})
            self.assertFalse(form.is_valid())
            self.assertIn('filing_mode', form.errors)

    def test_uncertain_2551q_still_shows_automation_support(self):
        from .registration_cards import card_actions
        cards = card_actions([{'code': '2551Q', 'uncertain': True}, {'code': '1701Q', 'uncertain': False}])
        self.assertTrue(cards[0]['can_prepare'])
        self.assertFalse(cards[1]['can_prepare'])
