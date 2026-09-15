from copy import deepcopy
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, models, transaction
from django.test import TestCase
from django.urls import reverse
from audit.models import AuditEvent
from .models import Client, FormDefinition, ClientFilingProfile, WorkOrder, WorkOrderSnapshot, snapshot_digest
from .catalog_services import create_record, update_record
from .services import create_work_order, edit_work_order, transition_work_order, refresh_work_order_snapshot, get_preparation_automation_key
from .definitions import validate_period
from .reference_data.atc_2551qv2018 import ALLOWED_ATCS
from .test_support import fake_client_data, make_profile, order_data
from .validators import safe_filename_component


class ClientArchitectureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username='test_admin', password='fake-only-password')
        cls.profile = make_profile(cls.actor)

    def make_order(self, profile=None, **changes):
        return create_work_order(actor=self.actor, client_filing_profile_id=(profile or self.profile).pk, data=order_data(**changes))

    def ready(self, order):
        return transition_work_order(work_order_id=order.pk, actor=self.actor, expected_version=order.version, target='READY_TO_PREPARE')

    def test_multiple_profiles_and_unique_pair(self):
        planned = create_record(model=ClientFilingProfile, actor=self.actor, data=dict(client=self.profile.client, form_definition=FormDefinition.objects.get(form_code='1701Q')))
        self.assertEqual(self.profile.client.filing_profiles.count(), 2)
        with self.assertRaises(ValidationError):
            create_record(model=ClientFilingProfile, actor=self.actor, data=dict(client=planned.client, form_definition=planned.form_definition))
        with self.assertRaises(IntegrityError), transaction.atomic():
            # Deliberately bypass model checks to verify the database boundary.
            models.Model.save(ClientFilingProfile(client=planned.client, form_definition=planned.form_definition), force_insert=True)

    def test_client_type_is_explicit(self):
        for value in ('', 'CORPORATION', None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                create_record(model=Client, actor=self.actor, data=fake_client_data(client_type=value))
        self.assertFalse(Client._meta.get_field('client_type').has_default())
        data = fake_client_data(); data.pop('client_type')
        with self.assertRaises(ValidationError):
            create_record(model=Client, actor=self.actor, data=data)

    def test_identifiers_are_text_and_leading_zeros_survive(self):
        order = self.make_order(); order.refresh_from_db()
        self.assertEqual(order.combined_tin, '00100200300000')
        self.assertEqual(order.client.combined_tin, order.combined_tin)
        self.assertEqual(order.current_snapshot.data['client']['tin4'], '00000')
        for field in ('tin1','tin2','tin3','tin4','rdo_code','zip_code','telephone_number'):
            self.assertIsInstance(getattr(order.client, field), str)
        for field in ('tin1','tin2','tin3','tin4'):
            for value in ('12', '123456', '1-2', '1 2', 'ABC', '１２３', 123, '123\n'):
                with self.subTest(field=field,value=value), self.assertRaises(ValidationError):
                    create_record(model=Client, actor=self.actor, data=fake_client_data(**{field:value}))

    def test_rdo_formats_and_normalization(self):
        for source, expected in (('047','047'),('050','050'),('53A','53A'),(' 53b ','53B'),('54a','54A'),('54B','54B'),('ABC','ABC')):
            record=create_record(model=Client, actor=self.actor, data=fake_client_data(rdo_code=source))
            record.refresh_from_db(); self.assertEqual(record.rdo_code,expected)
        for bad in ('47','0050','53-A','ABC1','', '５３A'):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                create_record(model=Client, actor=self.actor, data=fake_client_data(rdo_code=bad))

    def test_required_client_fields(self):
        for name in ('registered_name','registered_address','zip_code','line_of_business'):
            for value in ('', ' ', None):
                with self.subTest(name=name,value=value), self.assertRaises(ValidationError):
                    create_record(model=Client, actor=self.actor, data=fake_client_data(**{name:value}))

    def test_every_atc_is_accepted(self):
        self.assertEqual(len(ALLOWED_ATCS),22)
        for atc in ALLOWED_ATCS:
            with self.subTest(atc=atc):
                order=self.make_order(form_data={'atc_code':atc})
                order.refresh_from_db(); self.assertEqual(order.atc_code,atc)

    def test_friendly_atc_normalizes(self):
        for atc in ('PT010','pt010','pt 010','  pt 010  '):
            order=self.make_order(form_data={'atc_code':atc})
            self.assertEqual(order.form_data,{'atc_code':'PT 010'})
            self.assertEqual(order.current_snapshot.data['filing']['form_data'],order.form_data)

    def test_invalid_atc_and_schema_rejected(self):
        for atc in ('',' ','-','PT 999','PT 01','PT 0101','PT  010','PT\t010','PT ０１０'):
            with self.subTest(atc=atc),self.assertRaises(ValidationError):
                self.make_order(form_data={'atc_code':atc})
        for data in ([], None, 'PT 010', {'unknown':'x'}):
            with self.subTest(data=data),self.assertRaises(ValidationError):
                self.make_order(form_data=data)

    def test_no_atc_default_or_inference(self):
        self.assertIsNone(self.profile.default_atc_code)
        self.assertFalse(WorkOrder._meta.get_field('atc_code').has_default())
        profile=make_profile(self.actor,client_data={'registered_name':'PT 010','line_of_business':'PT 010'})
        with self.assertRaises(ValidationError):
            self.make_order(profile,form_data={})
        self.assertEqual(WorkOrder.objects.count(),0)

    def test_only_explicit_profile_atc_default_is_used(self):
        profile=make_profile(self.actor,default_atc_code='pt010')
        self.assertEqual(self.make_order(profile,form_data={}).atc_code,'PT 010')
        self.assertEqual(self.make_order(profile,form_data={'atc_code':'PT 040'}).atc_code,'PT 040')
        with self.assertRaises(ValidationError):
            make_profile(self.actor,default_atc_code='PT 010',default_form_data={'atc_code':'PT 040'})

    def test_2551_calendar_scope(self):
        for data in ({'year_end_month':'06'},{'calendar_or_fiscal':'FISCAL'},{'year_end_month':12}):
            with self.subTest(data=data),self.assertRaises(ValidationError):
                make_profile(self.actor,**data)
        for year in ('0000','026','20260','20A6','２０２６','2026\n',2026):
            with self.subTest(year=year),self.assertRaises(ValidationError):
                self.make_order(filing_year=year)
        for quarter in (0,5,-1,None):
            with self.subTest(quarter=quarter),self.assertRaises(ValidationError):
                self.make_order(filing_quarter=quarter)
        with self.assertRaises(ValidationError): self.make_order(filing_month=1)
        with self.assertRaises(ValidationError): self.make_order(zero_filing=False)

    def test_generic_period_validation_isolated(self):
        validate_period('MONTHLY','2026',3,None)
        validate_period('ANNUAL','2026',None,None)
        for args in (('MONTHLY','2026',None,None),('ANNUAL','2026',None,1),('QUARTERLY','2026',1,1)):
            with self.assertRaises(ValidationError): validate_period(*args)

    def test_exact_derived_names(self):
        profile=make_profile(self.actor,client_data={'tin1':'650','tin2':'703','tin3':'312'})
        order=self.make_order(profile)
        self.assertEqual(order.expected_return_period,'122026Q3')
        self.assertEqual(order.expected_saved_return_name,'65070331200000-2551Qv2018-122026Q3')
        self.assertEqual(order.expected_xml_filename,order.expected_saved_return_name+'.xml')

    def test_no_editable_duplicate_sources_or_derived_overrides(self):
        order=self.make_order()
        for field in ('registered_name','tin1','rdo_code','form_code','atc_code','client_name'):
            self.assertFalse(WorkOrder._meta.get_field(field).editable)
            with self.assertRaises(ValidationError):
                edit_work_order(work_order_id=order.pk,actor=self.actor,expected_version=1,changes={field:'x'})
        for field in ('client','client_filing_profile','expected_saved_return_name','status','approved_for_submission','saved_xml_path'):
            with self.assertRaises(ValidationError): self.make_order(**{field:'x'})

    def test_inactive_sources_block_new_and_ready(self):
        order=self.make_order(zero_filing_approved=True)
        for record in (self.profile,self.profile.client,self.profile.form_definition):
            updated=update_record(model=type(record),pk=record.pk,actor=self.actor,expected_version=record.version,changes={'is_active':False})
            with self.assertRaises(ValidationError): self.make_order()
            with self.assertRaises(ValidationError): self.ready(order)
            update_record(model=type(record),pk=record.pk,actor=self.actor,expected_version=updated.version,changes={'is_active':True})

    def test_planned_form_has_no_automation_and_cannot_queue(self):
        profile=make_profile(self.actor,key='planned_1701q')
        self.assertEqual(profile.form_definition.form_version,'')
        self.assertEqual(profile.form_definition.automation_key,'')
        order=self.make_order(profile,zero_filing=False,form_data={})
        self.assertEqual(order.status,'DRAFT')
        self.assertEqual(order.expected_xml_filename,'')
        with self.assertRaises(ValidationError): self.ready(order)
        with self.assertRaises(ValidationError):
            update_record(model=FormDefinition,pk=profile.form_definition_id,actor=self.actor,expected_version=1,changes={'preparation_automation_available':True})
        with self.assertRaises(ValidationError):
            update_record(model=FormDefinition,pk=profile.form_definition_id,actor=self.actor,expected_version=1,changes={'automation_key':'PREPARE_2551QV2018_ZERO'})

    def test_known_definition_identity_and_submission_guard(self):
        form=self.profile.form_definition
        for changes in ({'automation_key':'WRONG'},{'form_selection_text':'WRONG'},{'submission_automation_available':True},{'definition_key':'planned_1701q'}):
            with self.subTest(changes=changes),self.assertRaises(ValidationError):
                update_record(model=FormDefinition,pk=form.pk,actor=self.actor,expected_version=1,changes=changes)

    def test_profile_cannot_be_reassigned(self):
        with self.assertRaises(ValidationError):
            update_record(model=ClientFilingProfile,pk=self.profile.pk,actor=self.actor,expected_version=1,changes={'form_definition':FormDefinition.objects.get(form_code='1701Q')})

    def test_snapshot_creation_hash_and_audit(self):
        order=self.make_order(); snap=order.current_snapshot
        self.assertEqual(snap.revision,1)
        self.assertEqual(snap.sha256,snapshot_digest(snap.data,snap.source_versions))
        self.assertEqual(snap.data['client']['id'],str(order.client_id))
        self.assertEqual(order.audit_events.get().snapshot,snap)
        self.assertEqual(snap.created_by,self.actor)

    def test_source_change_preserves_snapshot_and_blocks_queue_until_refresh(self):
        order=self.make_order(zero_filing_approved=True)
        original=deepcopy(order.current_snapshot.data)
        update_record(model=Client,pk=order.client_id,actor=self.actor,expected_version=1,changes={'registered_name':'CHANGED FAKE'})
        order.refresh_from_db()
        self.assertEqual(order.current_snapshot.data,original)
        self.assertEqual(order.registered_name,original['client']['registered_name'])
        with self.assertRaises(ValidationError): self.ready(order)
        refreshed=refresh_work_order_snapshot(work_order_id=order.pk,actor=self.actor,expected_version=1)
        self.assertEqual(refreshed.current_snapshot.revision,2)
        self.assertEqual(refreshed.registered_name,'CHANGED FAKE')
        self.assertFalse(refreshed.zero_filing_approved)
        self.assertEqual(refreshed.snapshots.get(revision=1).data,original)
        with self.assertRaises(ValidationError): self.ready(refreshed)
        reviewed=edit_work_order(work_order_id=order.pk,actor=self.actor,expected_version=2,changes={'zero_filing_approved':True})
        self.assertEqual(get_preparation_automation_key(self.ready(reviewed)),'PREPARE_2551QV2018_ZERO')

    def test_edit_does_not_silently_refresh_client(self):
        order=self.make_order()
        update_record(model=Client,pk=order.client_id,actor=self.actor,expected_version=1,changes={'registered_name':'NEW FAKE'})
        edited=edit_work_order(work_order_id=order.pk,actor=self.actor,expected_version=1,changes={'filing_quarter':4})
        self.assertEqual(edited.registered_name,'FAKE TEST CLIENT')
        self.assertEqual(edited.current_snapshot.source_versions['client'],1)
        self.assertEqual(edited.expected_return_period,'122026Q4')

    def test_snapshots_are_immutable(self):
        snap=self.make_order().current_snapshot
        for operation in (lambda:snap.save(_service_write=True),lambda:snap.delete(),lambda:WorkOrderSnapshot.objects.filter(pk=snap.pk).update(data={}),lambda:WorkOrderSnapshot.objects.all().delete()):
            with self.assertRaises(ValidationError):operation()
        snap.sha256='0'*64
        with self.assertRaises(ValidationError):snap.full_clean()

    def test_ready_requires_confirmation_and_exact_route(self):
        order=self.make_order()
        with self.assertRaises(ValidationError):self.ready(order)
        with self.assertRaises(ValidationError):get_preparation_automation_key(order)
        order=edit_work_order(work_order_id=order.pk,actor=self.actor,expected_version=1,changes={'zero_filing_approved':True})
        ready=self.ready(order)
        self.assertEqual(get_preparation_automation_key(ready),'PREPARE_2551QV2018_ZERO')
        update_record(model=Client,pk=order.client_id,actor=self.actor,expected_version=1,changes={'is_active':False})
        with self.assertRaises(ValidationError):get_preparation_automation_key(ready)

    def test_enabled_transitions_and_edit_returns_draft(self):
        order=self.make_order(zero_filing_approved=True)
        for target in [s for s in WorkOrder.Status.values if s!='READY_TO_PREPARE']+['UNKNOWN']:
            with self.assertRaises(ValidationError):
                transition_work_order(work_order_id=order.pk,actor=self.actor,expected_version=1,target=target)
        ready=self.ready(order)
        draft=edit_work_order(work_order_id=order.pk,actor=self.actor,expected_version=ready.version,changes={'filing_quarter':4})
        self.assertEqual(draft.status,'DRAFT')
        ready=self.ready(draft)
        draft=transition_work_order(work_order_id=order.pk,actor=self.actor,expected_version=ready.version,target='DRAFT')
        self.assertEqual(draft.status,'DRAFT')

    def test_normalized_noop_edit_does_not_increment(self):
        order=self.ready(self.make_order(zero_filing_approved=True))
        result=edit_work_order(work_order_id=order.pk,actor=self.actor,expected_version=2,changes={'form_data':{'atc_code':'pt010'}})
        self.assertEqual(result.version,2);self.assertEqual(result.status,'READY_TO_PREPARE')
        self.assertEqual(result.snapshots.count(),1)

    def test_stale_versions_rejected(self):
        order=self.make_order()
        edit_work_order(work_order_id=order.pk,actor=self.actor,expected_version=1,changes={'filing_quarter':4})
        with self.assertRaises(ValidationError):self.ready(order)
        with self.assertRaises(ValidationError):
            edit_work_order(work_order_id=order.pk,actor=self.actor,expected_version=1,changes={'filing_quarter':2})
        client=self.profile.client
        update_record(model=Client,pk=client.pk,actor=self.actor,expected_version=1,changes={'trade_name':'FAKE NEW'})
        with self.assertRaises(ValidationError):
            update_record(model=Client,pk=client.pk,actor=self.actor,expected_version=1,changes={'trade_name':'STALE'})

    def test_audit_failure_rolls_back_order_snapshot_and_config(self):
        with patch('workorders.services.AuditEvent.objects.create',side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):self.make_order()
            with self.assertRaises(RuntimeError):
                update_record(model=Client,pk=self.profile.client_id,actor=self.actor,expected_version=1,changes={'trade_name':'FAKE NEW'})
        self.assertEqual(WorkOrder.objects.count(),0);self.assertEqual(WorkOrderSnapshot.objects.count(),0)
        self.profile.client.refresh_from_db();self.assertEqual(self.profile.client.version,1)

    def test_permissions(self):
        order=self.make_order()
        for actor in (AnonymousUser(),get_user_model().objects.create_user(username='unassigned')):
            with self.assertRaises(PermissionDenied):
                create_work_order(actor=actor,client_filing_profile_id=self.profile.pk,data=order_data())
            with self.assertRaises(PermissionDenied):
                edit_work_order(work_order_id=order.pk,actor=actor,expected_version=1,changes={})
            with self.assertRaises(PermissionDenied):
                create_record(model=Client,actor=actor,data=fake_client_data())

    def test_direct_and_bulk_writes_blocked(self):
        for obj in (self.profile,self.profile.client,self.profile.form_definition,self.make_order()):
            for operation in (lambda:obj.save(),lambda:obj.delete(),lambda:type(obj).objects.all().update(version=2),lambda:type(obj).objects.bulk_update([obj],['version']),lambda:type(obj).objects.all().delete()):
                with self.assertRaises(ValidationError):operation()

    def test_database_and_model_cross_field_guards(self):
        order=self.make_order()
        for data in ({'status':'SUBMITTED'},{'status':'READY_TO_PREPARE'},{'filing_quarter':5},{'filing_month':1},{'approved_for_submission':True},{'version':0},{'client_id':None}):
            with self.subTest(data=data),self.assertRaises(IntegrityError),transaction.atomic():
                models.QuerySet.update(WorkOrder.objects.filter(pk=order.pk),**data)
        order.client=make_profile(self.actor).client
        with self.assertRaises(ValidationError):order.full_clean()
        order.refresh_from_db();order.saved_xml_path='C:\\eBIRForms\\savefile\\fake.xml'
        with self.assertRaises(ValidationError):order.full_clean()

    def test_safe_windows_filename(self):
        for value in ('../A\\B:C*D?E','CON','con.txt','LPT1','...','x'*300):
            name=safe_filename_component(value)
            self.assertTrue(name);self.assertNotRegex(name,r'[\\/:*?"<>|]')
            self.assertLessEqual(len(name),101)

    def test_admin_configuration_writes_are_audited(self):
        self.client.force_login(self.actor)
        response=self.client.post(reverse('admin:workorders_client_add'),{**fake_client_data(client_code='FAKE-ADMIN',rdo_code='53a'), 'is_active':'on','_save':'Save'})
        self.assertEqual(response.status_code,302)
        taxpayer=Client.objects.get(client_code='FAKE-ADMIN')
        self.assertEqual(taxpayer.rdo_code,'53A')
        self.assertEqual(taxpayer.audit_events.get().kind,'CONFIG_CREATED')
        response=self.client.post(reverse('admin:workorders_client_change',args=[taxpayer.pk]),{**fake_client_data(client_code='FAKE-ADMIN',trade_name='FAKE UPDATED'), 'is_active':'on','expected_version':1,'_save':'Save'})
        self.assertEqual(response.status_code,302)
        taxpayer.refresh_from_db();self.assertEqual(taxpayer.version,2)
        response=self.client.post(reverse('admin:workorders_client_change',args=[taxpayer.pk]),{**fake_client_data(client_code='FAKE-ADMIN'), 'expected_version':1})
        self.assertContains(response,'Reload before saving')

    def test_admin_workorder_and_snapshot_protection(self):
        order=self.make_order(zero_filing_approved=True)
        self.client.force_login(self.actor)
        for model, pk in (('workorder',order.pk),('workordersnapshot',order.current_snapshot_id),('clientfilingprofile',self.profile.pk),('formdefinition',self.profile.form_definition_id)):
            self.assertEqual(self.client.get(reverse(f'admin:workorders_{model}_change',args=[pk])).status_code,200)
            self.assertEqual(self.client.post(reverse(f'admin:workorders_{model}_delete',args=[pk]),{'post':'yes'}).status_code,403)
        response=self.client.get(reverse('admin:workorders_workorder_change',args=[order.pk]))
        for field in ('registered_name','tin1','status','prepared_pdf','saved_xml_path','lease_token'):
            self.assertNotContains(response,f'name="{field}"')
        self.assertEqual(self.client.get(reverse('admin:workorders_workorder_add')).status_code,403)
        self.client.post(reverse('admin:workorders_workorder_changelist'),{'action':'mark_ready','_selected_action':str(order.pk)})
        order.refresh_from_db();self.assertEqual(order.status,'READY_TO_PREPARE')

    def test_model_clean_rejects_ready_with_stale_sources(self):
        order=self.make_order(zero_filing_approved=True)
        update_record(model=ClientFilingProfile,pk=self.profile.pk,actor=self.actor,expected_version=1,changes={'default_atc_code':'PT 040'})
        order.status='READY_TO_PREPARE'
        with self.assertRaises(ValidationError):order.full_clean()

    def test_forced_planned_availability_never_routes_to_2551(self):
        profile=make_profile(self.actor,key='planned_1701q')
        order=self.make_order(profile,form_data={},zero_filing_approved=True)
        models.QuerySet.update(FormDefinition.objects.filter(pk=profile.form_definition_id),preparation_automation_available=True,automation_key='PREPARE_2551QV2018_ZERO')
        with self.assertRaises(ValidationError):self.ready(order)

    def test_transition_audit_failure_rolls_back(self):
        order=self.make_order(zero_filing_approved=True)
        with patch('workorders.services.AuditEvent.objects.create',side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):self.ready(order)
        order.refresh_from_db()
        self.assertEqual(order.status,'DRAFT');self.assertEqual(order.version,1)

    def test_existing_form_selects_only_active_2551_profiles(self):
        from .forms import WorkOrderForm
        planned=make_profile(self.actor,key='planned_1701q')
        inactive=make_profile(self.actor,is_active=False)
        selected=set(WorkOrderForm().fields['client_filing_profile'].queryset.values_list('pk',flat=True))
        self.assertEqual(selected,{self.profile.pk})
        self.assertNotIn(planned.pk,selected);self.assertNotIn(inactive.pk,selected)

    def test_read_only_workorder_admin_post_rejected(self):
        order=self.make_order()
        self.client.force_login(self.actor)
        self.assertEqual(self.client.post(reverse('admin:workorders_workorder_change',args=[order.pk]),{'filing_year':'2025'}).status_code,403)
        order.refresh_from_db();self.assertEqual(order.filing_year,'2026')
