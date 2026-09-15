import hashlib
import io
import json
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import models, transaction, IntegrityError, connections
from django.test import TestCase, TransactionTestCase, override_settings, Client as HttpClient
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfWriter
from audit.models import AuditEvent
from workorders.models import WorkOrder, WorkOrderSnapshot
from workorders.test_support import make_profile,order_data,ensure_transactional_form
from workorders.services import create_work_order,transition_work_order,edit_work_order,refresh_work_order_snapshot
from workorders.catalog_services import update_record
from .services import create_agent,disable_agent,rotate_agent_token
from .models import Agent,PreparationAttempt
from . import worker_services


def two_page_pdf(pages=2):
    output=io.BytesIO();writer=PdfWriter()
    for _ in range(pages):writer.add_blank_page(width=612,height=792)
    writer.write(output)
    return output.getvalue()


class WorkerApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor=get_user_model().objects.create_superuser(username='fake_api_admin',password='fake-only-password')
        cls.profile=make_profile(cls.actor,client_data={'tin1':'650','tin2':'703','tin3':'312','trade_name':'ABC TEST COMPANY'})
        cls.agent,cls.token=create_agent(actor=cls.actor,name='FAKE-HYPERV')
        cls.other,cls.other_token=create_agent(actor=cls.actor,name='OTHER-FAKE-VM')

    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='ebir-api-test-')
        self.addCleanup(self.folder.cleanup)
        self.override=override_settings(MEDIA_ROOT=self.folder.name)
        self.override.enable();self.addCleanup(self.override.disable)
        self.client=HttpClient(enforce_csrf_checks=True)
        self.client.defaults['HTTP_AUTHORIZATION']='Bearer '+self.token

    def make_order(self):
        order=create_work_order(actor=self.actor,client_filing_profile_id=self.profile.pk,data=order_data(filing_quarter=2,zero_filing_approved=True))
        return transition_work_order(work_order_id=order.pk,actor=self.actor,expected_version=1,target='READY_TO_PREPARE')

    def claim(self,request_id=None):
        return self.client.post(reverse('automation_api:claim'),data=json.dumps({'request_id':str(request_id or uuid.uuid4()),'automation_keys':['PREPARE_2551QV2018_ZERO']}),content_type='application/json')

    def job(self):
        self.make_order();response=self.claim();self.assertEqual(response.status_code,200,response.content)
        return response.json()

    def upload(self,job,data=None,**headers):
        data=two_page_pdf() if data is None else data
        return self.client.put(job['PdfUploadUrl'],data=data,content_type='application/pdf',HTTP_X_LEASE_TOKEN=job['LeaseToken'],HTTP_X_PDF_SHA256=hashlib.sha256(data).hexdigest(),**headers)

    def result(self,job,**changes):
        data={'lease_token':job['LeaseToken'],'PreparationStatusOutput':'AWAITING_SUBMISSION_APPROVAL','PreparedPdfPath':job['ExpectedPdfPath'],'SavedXmlPath':job['ExpectedXmlPath']}
        data.update(changes)
        return self.client.post(job['ResultUrl'],data=json.dumps(data),content_type='application/json')

    def test_bearer_only_authentication_and_no_cache(self):
        for header in ('','Bearer wrong','Basic '+self.token):
            client=HttpClient(HTTP_AUTHORIZATION=header)
            client.force_login(self.actor)
            response=client.get(reverse('automation_api:health'))
            self.assertEqual(response.status_code,401)
            self.assertIn('no-store',response.headers['Cache-Control'])
        response=self.client.get(reverse('automation_api:health'))
        self.assertEqual(response.status_code,200);self.assertFalse(response.json()['submission_enabled'])
        self.agent.refresh_from_db();self.assertIsNotNone(self.agent.last_seen_at)
        disable_agent(actor=self.actor,agent_id=self.agent.pk)
        self.assertEqual(self.client.get(reverse('automation_api:health')).status_code,401)

    def test_rotated_token_revokes_api_access(self):
        rotate_agent_token(actor=self.actor,agent_id=self.agent.pk)
        self.assertEqual(self.client.get(reverse('automation_api:health')).status_code,401)

    def test_claim_is_post_only_and_validated(self):
        self.assertEqual(self.client.get(reverse('automation_api:claim')).status_code,405)
        for body in ({},{'request_id':'bad','automation_keys':[]},{'request_id':str(uuid.uuid4()),'automation_keys':['1701Q']},{'request_id':str(uuid.uuid4()),'automation_keys':['PREPARE_2551QV2018_ZERO'],'status':'SUBMITTED'}):
            response=self.client.post(reverse('automation_api:claim'),data=json.dumps(body),content_type='application/json')
            self.assertEqual(response.status_code,400)
        self.assertEqual(self.claim().status_code,204)

    def test_all_twenty_inputs_use_snapshot_and_quarter_text(self):
        job=self.job();data=job['Inputs']
        self.assertEqual(len(data),20)
        self.assertTrue(all(isinstance(value,str) for value in data.values()))
        self.assertEqual(data['TIN4'],'00000');self.assertEqual(data['FilingQuarter'],'2')
        self.assertEqual(data['ClientNameSafe'],'ABC_TEST_COMPANY')
        self.assertEqual(job['ExpectedSavedReturnName'],'65070331200000-2551Qv2018-122026Q2')
        self.assertTrue(data['OutputFolder'].startswith('C:\\TaxAutomation\\Working\\WO-'))
        self.assertEqual(job['AutomationKey'],'PREPARE_2551QV2018_ZERO')
        order=WorkOrder.objects.get();self.assertEqual(order.status,'PROCESSING_PREPARATION')
        event=order.audit_events.get(kind='API_LEASE')
        self.assertIsNone(event.actor);self.assertEqual(event.performed_by_agent,self.agent)
        self.assertNotIn(self.token,str(list(AuditEvent.objects.values())))

    def test_fifo_idempotence_and_single_global_execution(self):
        first=self.make_order();second=self.make_order();request_id=uuid.uuid4()
        one=self.claim(request_id);two=self.claim(request_id)
        self.assertEqual(one.json(),two.json())
        self.assertEqual(one.json()['WorkOrderId'],first.work_order_id)
        self.assertEqual(PreparationAttempt.objects.count(),1)
        self.assertEqual(self.claim().json()['error'],'worker_busy')
        self.client.defaults['HTTP_AUTHORIZATION']='Bearer '+self.other_token
        self.assertEqual(self.claim(request_id).status_code,409)
        self.assertEqual(self.claim().status_code,409)
        second.refresh_from_db();self.assertEqual(second.status,'READY_TO_PREPARE')

    def test_stale_snapshot_is_not_claimed(self):
        order=self.make_order()
        update_record(model=type(self.profile.client),pk=self.profile.client_id,actor=self.actor,expected_version=1,changes={'trade_name':'CHANGED FAKE'})
        self.assertEqual(self.claim().status_code,204)
        order.refresh_from_db();self.assertEqual(order.status,'READY_TO_PREPARE')

    def test_claim_audit_failure_rolls_back(self):
        order=self.make_order()
        with patch('automation_api.worker_services.AuditEvent.objects.create',side_effect=RuntimeError('SECRET TEST VALUE')):
            response=self.claim()
        self.assertEqual(response.status_code,500)
        self.assertNotIn(b'SECRET TEST VALUE',response.content)
        self.assertEqual(PreparationAttempt.objects.count(),0)
        order.refresh_from_db();self.assertEqual(order.status,'READY_TO_PREPARE')

    def test_claimed_work_order_cannot_edit_or_refresh(self):
        self.job();order=WorkOrder.objects.get()
        with self.assertRaises(ValidationError):edit_work_order(work_order_id=order.pk,actor=self.actor,expected_version=order.version,changes={'filing_quarter':3})
        with self.assertRaises(ValidationError):refresh_work_order_snapshot(work_order_id=order.pk,actor=self.actor,expected_version=order.version)
        self.client.force_login(self.actor)
        self.assertEqual(self.client.get(reverse('workorders:edit',args=[order.pk])).status_code,403)

    def test_wrong_worker_and_wrong_lease_cannot_report_or_upload(self):
        job=self.job()
        self.client.defaults['HTTP_AUTHORIZATION']='Bearer '+self.other_token
        self.assertEqual(self.upload(job).status_code,404)
        self.assertEqual(self.result(job).status_code,404)
        self.client.defaults['HTTP_AUTHORIZATION']='Bearer '+self.token
        job['LeaseToken']=str(uuid.uuid4())
        self.assertEqual(self.upload(job).status_code,403)
        self.assertEqual(self.result(job).status_code,403)
        self.assertEqual(list(Path(self.folder.name).rglob('*.pdf')),[])

    def test_expired_lease_never_auto_requeues(self):
        job=self.job();attempt=PreparationAttempt.objects.get()
        models.QuerySet.update(PreparationAttempt.objects.filter(pk=attempt.pk),lease_expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.upload(job).status_code,409)
        self.assertEqual(self.result(job).status_code,409)
        self.assertEqual(self.claim(attempt.pk).json()['error'],'lease_expired')
        self.assertEqual(self.claim().json()['error'],'worker_busy')
        self.assertEqual(WorkOrder.objects.get().status,'PROCESSING_PREPARATION')

    def test_renew_owned_live_lease(self):
        job=self.job()
        response=self.client.post(job['RenewUrl'],data=json.dumps({'lease_token':job['LeaseToken']}),content_type='application/json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(AuditEvent.objects.filter(kind='LEASE_RENEWED').count(),1)
        diagnostic=self.client.get(reverse('automation_api:current')).json()
        self.assertNotIn('Inputs',diagnostic);self.assertNotIn('LeaseToken',diagnostic)

    def test_success_requires_upload_and_exact_xml_pdf_paths(self):
        job=self.job()
        self.assertEqual(self.result(job).json()['error'],'pdf_required')
        response=self.upload(job);self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(WorkOrder.objects.get().status,'PROCESSING_PREPARATION')
        for value in ('C:\\eBIRForms\\savefile\\wrong.xml','C:\\eBIRForms\\savefile\\..\\wrong.xml','\\\\server\\wrong.xml'):
            self.assertEqual(self.result(job,SavedXmlPath=value).status_code,400)
        response=self.result(job);self.assertEqual(response.status_code,200,response.content)
        order=WorkOrder.objects.get();self.assertEqual(order.status,'AWAITING_SUBMISSION_APPROVAL')
        self.assertEqual(order.saved_xml_path,job['ExpectedXmlPath'])
        self.assertFalse(order.approved_for_submission)
        self.assertEqual(PreparationAttempt.objects.get().state,'SUCCEEDED')
        self.assertEqual(PreparationAttempt.objects.get().execution_slot,None)

    def test_pdf_upload_is_idempotent_and_cannot_replace(self):
        job=self.job();self.assertEqual(self.upload(job).status_code,200)
        self.assertEqual(self.upload(job).status_code,200)
        self.assertEqual(len(list(Path(self.folder.name).rglob('*.pdf'))),1)
        changed=two_page_pdf()+b'\n'
        self.assertEqual(self.upload(job,changed).status_code,409)
        self.assertEqual(AuditEvent.objects.filter(kind='PDF_UPLOADED').count(),1)

    def test_bad_pdf_page_count_hash_and_size_rejected(self):
        job=self.job()
        for data in (b'not a PDF',b'%PDF-1.7\nnot valid',two_page_pdf(1),two_page_pdf(3)):
            self.assertEqual(self.upload(job,data).status_code,400)
        data=two_page_pdf()
        response=self.client.put(job['PdfUploadUrl'],data=data,content_type='application/pdf',HTTP_X_LEASE_TOKEN=job['LeaseToken'],HTTP_X_PDF_SHA256='0'*64)
        self.assertEqual(response.status_code,400)
        with patch('automation_api.worker_services.MAX_PDF_BYTES',32):
            self.assertEqual(self.upload(job,data).status_code,413)
        self.assertFalse(WorkOrder.objects.get().prepared_pdf)

    def test_upload_audit_failure_cleans_uncommitted_file(self):
        job=self.job()
        with patch('automation_api.worker_services.AuditEvent.objects.create',side_effect=RuntimeError('test')):
            self.assertEqual(self.upload(job).status_code,500)
        self.assertFalse(WorkOrder.objects.get().prepared_pdf)
        self.assertEqual(list(Path(self.folder.name).rglob('*.pdf')),[])

    def test_missing_or_changed_stored_pdf_blocks_success(self):
        job=self.job();self.upload(job)
        path=worker_services.private_pdf_path(WorkOrder.objects.get())
        path.write_bytes(b'changed')
        self.assertEqual(self.result(job).json()['error'],'pdf_changed')
        path.unlink()
        self.assertEqual(self.result(job).json()['error'],'pdf_missing')
        self.assertEqual(WorkOrder.objects.get().status,'PROCESSING_PREPARATION')

    def test_prepared_xml_cannot_be_overwritten_by_another_job(self):
        first=self.make_order();second=self.make_order()
        job=self.claim().json();self.upload(job);self.result(job)
        self.assertEqual(self.claim().status_code,204)
        second.refresh_from_db();self.assertEqual(second.status,'READY_TO_PREPARE')
        with self.assertRaises(ValidationError):self.make_order()

    def test_completed_claim_and_result_retries_cannot_execute_again(self):
        job=self.job();self.upload(job);self.result(job)
        self.assertEqual(self.result(job).status_code,200)
        replay=self.claim(job['AttemptId']).json()
        self.assertEqual(replay['State'],'SUCCEEDED');self.assertNotIn('Inputs',replay)
        self.assertEqual(self.result(job,SavedXmlPath='changed').status_code,409)
        self.assertEqual(AuditEvent.objects.filter(kind='PREPARATION_RESULT').count(),1)

    def test_failure_result_releases_slot_without_retry(self):
        job=self.job()
        response=self.result(job,PreparationStatusOutput='PREPARATION_FAILED_XML_NOT_FOUND',PreparedPdfPath='',SavedXmlPath='')
        self.assertEqual(response.status_code,200)
        self.assertEqual(WorkOrder.objects.get().status,'PREPARATION_FAILED_XML_NOT_FOUND')
        self.assertEqual(self.claim().status_code,204)

    def test_submission_and_unknown_result_fields_rejected(self):
        job=self.job()
        for changes in ({'PreparationStatusOutput':'SUBMITTED'},{'ApprovedForSubmission':True},{'PreparationStatusOutput':'FAILED_SYSTEM','SavedXmlPath':'C:\\other.xml'}):
            self.assertEqual(self.result(job,**changes).status_code,400)

    def test_operator_recovery_requires_confirmation_and_version(self):
        self.job();attempt=PreparationAttempt.objects.get();order=attempt.work_order
        for confirmed,version in ((False,order.version),(True,order.version-1)):
            with self.assertRaises(ValidationError):
                worker_services.abandon(actor=self.actor,attempt_id=attempt.pk,expected_version=version,confirmed_stopped=confirmed)
        worker_services.abandon(actor=self.actor,attempt_id=attempt.pk,expected_version=order.version,confirmed_stopped=True)
        attempt.refresh_from_db();self.assertEqual(attempt.state,'ABANDONED')
        self.assertEqual(self.claim().status_code,204)

    def test_protected_pdf_download_permission_hash_and_headers(self):
        job=self.job();self.upload(job);self.result(job)
        order=WorkOrder.objects.get();url=reverse('workorders:prepared-pdf',args=[order.pk])
        anonymous=HttpClient();self.assertEqual(anonymous.get(url).status_code,302)
        user=get_user_model().objects.create_user(username='fake_pdf_viewer')
        anonymous.force_login(user);self.assertEqual(anonymous.get(url).status_code,403)
        user.groups.add(Group.objects.get(name='Approver'))
        response=anonymous.get(url);self.assertEqual(response.status_code,200)
        self.assertTrue(response['Content-Disposition'].startswith('attachment;'))
        self.assertEqual(response['X-Content-Type-Options'],'nosniff')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(b''.join(response.streaming_content),two_page_pdf())
        response.close()
        inline_url=url+'?inline=1'
        response=anonymous.get(inline_url)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response['Content-Disposition'].startswith('inline;'))
        self.assertEqual(response['X-Frame-Options'],'SAMEORIGIN')
        self.assertIn("frame-ancestors 'self'",response['Content-Security-Policy'])
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(b''.join(response.streaming_content),two_page_pdf())
        response.close()
        self.assertEqual(HttpClient().get(inline_url).status_code,302)
        detail=anonymous.get(reverse('workorders:detail',args=[order.pk]))
        self.assertContains(detail,'title="Prepared filing PDF"')
        self.assertContains(detail,inline_url+'#view=FitH')
        self.assertEqual(anonymous.get('/media/example.pdf').status_code,404)
        worker_services.private_pdf_path(order).write_bytes(b'changed')
        self.assertEqual(anonymous.get(url).status_code,404)
        self.assertEqual(anonymous.get(inline_url).status_code,404)

    def test_final_result_audit_failure_is_atomic(self):
        job=self.job();self.upload(job)
        with patch('automation_api.worker_services.AuditEvent.objects.create',side_effect=RuntimeError('test')):
            self.assertEqual(self.result(job).status_code,500)
        self.assertEqual(WorkOrder.objects.get().status,'PROCESSING_PREPARATION')
        self.assertEqual(PreparationAttempt.objects.get().state,'RUNNING')
        self.assertFalse(WorkOrder.objects.get().saved_xml_path)

    def test_database_rejects_final_state_without_artifacts(self):
        self.job()
        with self.assertRaises(IntegrityError),transaction.atomic():
            models.QuerySet.update(WorkOrder.objects.all(),status='AWAITING_SUBMISSION_APPROVAL')

    def test_provision_command_writes_only_ignored_secret_file(self):
        from django.core.management.base import CommandError
        with tempfile.TemporaryDirectory() as temporary,override_settings(BASE_DIR=Path(temporary)):
            target=Path(temporary)/'secrets'/'worker.json'
            output=io.StringIO()
            call_command('provision_worker',actor=self.actor.username,name='PROVISIONED-FAKE',token_file=str(target),stdout=output)
            credential=json.loads(target.read_text())
            self.assertNotIn(credential['Token'],output.getvalue())
            self.assertTrue(Agent.objects.get(name='PROVISIONED-FAKE').check_token(credential['Token']))
            with self.assertRaises(CommandError):
                call_command('provision_worker',actor=self.actor.username,name='SECOND-FAKE',token_file=str(target),stdout=output)
            self.assertFalse(Agent.objects.filter(name='SECOND-FAKE').exists())
            with self.assertRaises(CommandError):
                call_command('provision_worker',actor=self.actor.username,name='UNSAFE-FAKE',token_file=str(Path(temporary)/'public.json'),stdout=output)


class ConcurrentClaimTests(TransactionTestCase):
    def test_two_simultaneous_claims_cannot_share_or_double_execute(self):
        actor=get_user_model().objects.create_superuser(username='fake_concurrency',password='fake-only')
        ensure_transactional_form(actor)
        profile=make_profile(actor)
        for _ in range(2):
            order=create_work_order(actor=actor,client_filing_profile_id=profile.pk,data=order_data(zero_filing_approved=True))
            transition_work_order(work_order_id=order.pk,actor=actor,expected_version=1,target='READY_TO_PREPARE')
        _,token=create_agent(actor=actor,name='FAKE-CONCURRENT-VM')
        barrier=Barrier(2)
        def run():
            try:
                client=HttpClient(HTTP_AUTHORIZATION='Bearer '+token)
                barrier.wait(timeout=10)
                return client.post(reverse('automation_api:claim'),data=json.dumps({'request_id':str(uuid.uuid4()),'automation_keys':['PREPARE_2551QV2018_ZERO']}),content_type='application/json').status_code
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(lambda _:run(),range(2)))
        self.assertTrue(all(status in (200,409) for status in statuses),statuses)
        # SQLite may reject both contenders; a later retry must succeed once.
        if PreparationAttempt.objects.count()==0:
            client=HttpClient(HTTP_AUTHORIZATION='Bearer '+token)
            response=client.post(reverse('automation_api:claim'),data=json.dumps({'request_id':str(uuid.uuid4()),'automation_keys':['PREPARE_2551QV2018_ZERO']}),content_type='application/json')
            self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(PreparationAttempt.objects.filter(execution_slot=1).count(),1)
        self.assertEqual(WorkOrder.objects.filter(status='PROCESSING_PREPARATION').count(),1)
        self.assertEqual(WorkOrder.objects.filter(status='READY_TO_PREPARE').count(),1)
