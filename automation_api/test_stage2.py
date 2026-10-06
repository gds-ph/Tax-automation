import json
import uuid
from django.urls import reverse
from django.test import Client
from django.core.exceptions import ValidationError
from .test_worker_api import WorkerApiTests
from .stage2 import approve, claim_job, payload
from .models import Stage2Approval
from .worker_services import WorkerError, private_pdf_path
from workorders.models import WorkOrder


class Stage2Tests(WorkerApiTests):
    def test_editor_can_cancel_without_submission_or_worker_access(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        job = self.job(); self.upload(job); self.result(job)
        order = WorkOrder.objects.get()
        user = get_user_model().objects.create_user('cancel_editor')
        user.user_permissions.add(*Permission.objects.filter(codename__in=[
            'view_workorder', 'change_workorder']))
        browser = Client(); browser.force_login(user)
        detail = reverse('workorders:detail', args=[order.pk])
        self.assertContains(browser.get(detail), 'Cancel filing')
        self.assertNotContains(browser.get(detail), 'Download VM cancellation update')
        self.assertFalse(user.has_perm('automation_api.approve_stage2'))
        self.assertFalse(user.has_perm('automation_api.change_agent'))
        response = browser.post(reverse('workorders:cancel', args=[order.pk]),
                                {'expected_version': order.version, 'confirmed': 'yes'})
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, 'CANCELLED')
        self.assertTrue(order.cancellation_cleanup)
        self.assertEqual(browser.get(reverse('workorders:cancellation-worker-update')).status_code, 403)

    def test_approver_can_cancel_without_worker_permissions(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        job = self.job(); self.upload(job); self.result(job)
        order = WorkOrder.objects.get()
        user = get_user_model().objects.create_user('cancel_approver')
        user.user_permissions.add(*Permission.objects.filter(codename__in=[
            'view_workorder', 'view_prepared_pdf', 'approve_stage2']))
        self.assertFalse(user.has_perm('automation_api.change_agent'))
        browser = Client(); browser.force_login(user)
        detail = reverse('workorders:detail', args=[order.pk])
        self.assertContains(browser.get(detail), 'Cancel filing')
        self.assertNotContains(browser.get(detail), 'Download VM cancellation update')
        response = browser.post(reverse('workorders:cancel', args=[order.pk]),
                                {'expected_version': order.version, 'confirmed': 'yes'})
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, 'CANCELLED')
        self.assertTrue(order.cancellation_cleanup)
        self.assertEqual(browser.get(reverse('workorders:cancellation-worker-update')).status_code, 403)

    def test_cancellation_installer_is_admin_only(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from workorders.dashboard_actions import cancel_order
        job = self.job(); self.upload(job); self.result(job)
        order = WorkOrder.objects.get()
        url = reverse('workorders:cancellation-worker-update')
        detail = reverse('workorders:detail', args=[order.pk])
        browser = Client(); browser.force_login(self.actor)
        self.assertContains(browser.get(detail), 'Download VM cancellation update')
        response = browser.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()
        operator = get_user_model().objects.create_user('worker_operator', is_staff=True)
        operator.user_permissions.add(*Permission.objects.all())
        browser.force_login(operator)
        self.assertContains(browser.get(detail), 'Cancel filing')
        self.assertNotContains(browser.get(detail), 'Download VM cancellation update')
        self.assertEqual(browser.get(url).status_code, 403)
        cancel_order(actor=self.actor, work_order_id=order.pk, expected_version=order.version)
        self.assertNotContains(browser.get(detail), 'Download VM cancellation update')
        browser.force_login(self.actor)
        self.assertContains(browser.get(detail), 'Download VM cancellation update')

    def test_cancel_prepared_return_keeps_pdf_and_blocks_approval(self):
        from workorders.dashboard_actions import cancel_order
        job = self.job(); self.upload(job); self.result(job)
        order = WorkOrder.objects.get()
        path = private_pdf_path(order)
        before = path.read_bytes()
        xml = order.saved_xml_path
        cancel_order(actor=self.actor, work_order_id=order.pk, expected_version=order.version)
        order.refresh_from_db()
        self.assertEqual(order.status, 'CANCELLED')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(order.saved_xml_path, xml)
        browser = Client(); browser.force_login(self.actor)
        response = browser.get(reverse('workorders:prepared-pdf', args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        response.close()
        with self.assertRaises(WorkerError):
            approve(actor=self.actor, order_id=order.pk, version=order.version,
                    digest=order.prepared_pdf_sha256, submission_enabled=True)

    def test_dashboard_submission_recovery_download_and_stale_rejection(self):
        import io
        import zipfile
        from .stage2 import LIVE_KEY
        order, approval = self.live_prepared()
        attempt_id = uuid.uuid4()
        claim_job(self.agent, attempt_id, [LIVE_KEY])
        browser = Client()
        browser.force_login(self.actor)
        self.assertContains(browser.get(reverse('workorders:detail', args=[order.pk])),
                            'Retry interrupted submission')
        url = reverse('workorders:retry-submission', args=[order.pk])
        data = {'attempt_id': str(attempt_id), 'evidence_note': 'Stopped opening eBIRForms.'}
        self.assertEqual(browser.post(url, data).status_code, 400)
        approval.refresh_from_db()
        self.assertEqual(approval.state, 'RUNNING')
        data['confirmed_stopped_before_submit'] = 'on'
        response = browser.post(url, data)
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content))) as package:
            self.assertIn(str(attempt_id), package.read('Recover.cmd').decode())
            self.assertIn('Recover-Stage2BeforeSubmit.ps1', package.namelist())
        approval.refresh_from_db()
        self.assertEqual(approval.state, 'QUEUED')
        self.assertIsNone(approval.attempt_id)
        self.assertEqual(order.preparation_attempts.get(pk=attempt_id).state, 'ABANDONED')
        self.assertEqual(browser.post(url, data).status_code, 409)

    def test_dashboard_submission_recovery_requires_operator_and_csrf(self):
        from django.contrib.auth import get_user_model
        order, approval = self.live_prepared()
        url = reverse('workorders:retry-submission', args=[order.pk])
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.actor)
        self.assertEqual(browser.post(url, {}).status_code, 403)
        browser = Client()
        browser.force_login(get_user_model().objects.create_user('no_recovery_permission'))
        self.assertEqual(browser.post(url, {}).status_code, 403)

    def prepared(self):
        job=self.job(); self.upload(job); self.result(job)
        order=WorkOrder.objects.get()
        approval=approve(actor=self.actor, order_id=order.pk, version=order.version, digest=order.prepared_pdf_sha256)
        return order, approval

    def test_stage2_claim_replay_and_result(self):
        order, approval=self.prepared()
        self.assertIsNone(claim_job(self.other, uuid.uuid4()))
        request_id=uuid.uuid4()
        claimed=claim_job(self.agent, request_id)
        data=payload(claimed)
        self.assertEqual(data['Inputs']['ApprovalId'], str(approval.pk))
        self.assertFalse(data['Inputs']['SubmissionEnabled'])
        self.assertEqual(data['ExpectedPdfPath'], order.prepared_pdf_vm_path)
        self.assertEqual(claim_job(self.agent, request_id).attempt_id, request_id)
        self.assertEqual(self.claim().status_code, 204)
        from .worker_services import claim as preparation_claim
        with self.assertRaises(WorkerError):
            preparation_claim(agent=self.other, request_id=uuid.uuid4(),
                              automation_keys=['PREPARE_2551QV2018_ZERO'])
        with self.assertRaises(WorkerError):
            claim_job(self.other, request_id)
        url=data['ResultUrl']
        def report(status):
            return self.client.post(url, json.dumps({'lease_token':data['LeaseToken'], 'SubmissionStatus':status}), content_type='application/json')
        self.assertEqual(report('SUBMITTED').status_code, 400)
        self.assertEqual(report('APPROVED_READY_TO_SUBMIT').status_code, 200)
        self.assertEqual(report('APPROVED_READY_TO_SUBMIT').status_code, 200)
        self.assertEqual(report('FAILED_SYSTEM').status_code, 409)
        order.refresh_from_db()
        self.assertFalse(order.approved_for_submission)
        self.assertEqual(order.status,'AWAITING_SUBMISSION_APPROVAL')

    def test_archived_approval_does_not_block_polling(self):
        order, approval = self.prepared()
        order.is_archived = True
        order.save(_service_write=True)
        response = self.client.post('/api/agent/stage2/claim/', json.dumps({
            'request_id': str(uuid.uuid4()),
            'automation_keys': ['REVALIDATE_2551QV2018', 'SUBMIT_2551QV2018'],
        }), content_type='application/json')
        self.assertEqual(response.status_code, 204, response.content)
        approval.refresh_from_db()
        self.assertIsNone(approval.attempt_id)

    def test_stage2_tampered_pdf_and_stale_approval(self):
        order, approval=self.prepared()
        with self.assertRaises(ValidationError):
            approve(actor=self.actor, order_id=order.pk, version=order.version-1, digest=order.prepared_pdf_sha256)
        private_pdf_path(order).write_bytes(b'changed')
        with self.assertRaises(WorkerError):
            claim_job(self.agent, uuid.uuid4())
        self.assertEqual(Stage2Approval.objects.get().state, 'QUEUED')

    def test_approval_csrf_and_permission(self):
        order, approval=self.prepared()
        url=reverse('workorders:approve-stage2',args=[order.pk])
        browser=Client(enforce_csrf_checks=True)
        browser.force_login(self.actor)
        self.assertEqual(browser.post(url,{}).status_code,403)
        self.assertEqual(Client().post(url,{}).status_code,302)

    def live_prepared(self):
        job=self.job(); self.upload(job); self.result(job)
        order=WorkOrder.objects.get()
        approval=approve(actor=self.actor, order_id=order.pk, version=order.version,
                         digest=order.prepared_pdf_sha256, submission_enabled=True)
        return order, approval

    def test_live_mode_requires_explicit_approval_and_evidence(self):
        import base64, hashlib
        from .stage2 import LIVE_KEY, SUCCESS
        order, approval=self.live_prepared()
        self.assertIsNone(claim_job(self.agent, uuid.uuid4()))  # Old bridges cannot claim live work.
        data=payload(claim_job(self.agent, uuid.uuid4(), [LIVE_KEY]))
        self.assertTrue(data['Inputs']['SubmissionEnabled'])
        self.assertEqual(data['Inputs']['ApprovedSavedReturnName'], order.expected_saved_return_name)
        def report(status):
            return self.client.post(data['ResultUrl'], json.dumps({'lease_token':data['LeaseToken'], 'SubmissionStatus':status}), content_type='application/json')
        self.assertEqual(report(SUCCESS).status_code,409)
        image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        headers={'HTTP_X_LEASE_TOKEN':data['LeaseToken'], 'HTTP_X_SCREENSHOT_SHA256':hashlib.sha256(image).hexdigest()}
        uploaded=self.client.put(data['ScreenshotUploadUrl'],image,content_type='image/png',**headers)
        self.assertEqual(uploaded.status_code,200,uploaded.content)
        self.assertEqual(report(SUCCESS).status_code,200)
        self.assertEqual(report(SUCCESS).status_code,200)
        self.assertEqual(report('FAILED_SYSTEM').status_code,409)
        approval.refresh_from_db()
        self.assertEqual(approval.state,SUCCESS)
        self.assertIsNone(approval.attempt.execution_slot)
        browser=Client(); browser.force_login(self.actor)
        response=browser.get(reverse('workorders:submission-screenshot',args=[order.pk]))
        self.assertEqual(response.status_code,200)
        self.assertIn('no-store',response['Cache-Control'])
        response.close()
        self.assertEqual(Client().get(reverse('workorders:submission-screenshot',args=[order.pk])).status_code,302)
        self.assertContains(browser.get(reverse('workorders:detail',args=[order.pk])), 'Submitted - awaiting BIR confirmation')

    def test_rehearsal_approval_cannot_be_silently_upgraded(self):
        order, approval=self.prepared()
        with self.assertRaises(ValidationError):
            approve(actor=self.actor, order_id=order.pk, version=order.version,
                    digest=order.prepared_pdf_sha256, submission_enabled=True)

    def test_confirmed_pre_submit_recovery_preserves_attempt_and_approval(self):
        from .stage2 import LIVE_KEY, recover_before_submit
        from .models import PreparationAttempt
        order, approval = self.live_prepared()
        old_id = uuid.uuid4()
        claim_job(self.agent, old_id, [LIVE_KEY])
        recover_before_submit(actor=self.actor, approval_id=approval.pk, expected_attempt_id=old_id,
            confirmed_not_submitted=True, evidence_note='Operator saw failure before Submit was clicked; flows stopped.')
        old = PreparationAttempt.objects.get(pk=old_id)
        self.assertEqual(old.state, 'ABANDONED')
        self.assertIsNone(old.execution_slot)
        approval.refresh_from_db()
        self.assertEqual(approval.state,'QUEUED')
        self.assertIn(str(old_id),approval.comment)
        with self.assertRaises(WorkerError):
            claim_job(self.agent, old_id, [LIVE_KEY])
        new = claim_job(self.agent, uuid.uuid4(), [LIVE_KEY])
        self.assertEqual(new.pk,approval.pk)
        self.assertNotEqual(new.attempt_id,old_id)

    def test_pre_submit_recovery_rejects_missing_confirmation_and_evidence(self):
        from .stage2 import LIVE_KEY, recover_before_submit
        _, approval = self.live_prepared()
        old_id = uuid.uuid4()
        claim_job(self.agent, old_id, [LIVE_KEY])
        for confirmed, note in [(False,'stopped'), (True,'')]:
            with self.assertRaises(ValidationError):
                recover_before_submit(actor=self.actor,approval_id=approval.pk,expected_attempt_id=old_id,
                    confirmed_not_submitted=confirmed,evidence_note=note)
        approval.refresh_from_db()
        approval.success_screenshot='evidence.png'
        approval.save(_service_write=True)
        with self.assertRaises(ValidationError):
            recover_before_submit(actor=self.actor,approval_id=approval.pk,expected_attempt_id=old_id,
                confirmed_not_submitted=True,evidence_note='stopped')

    def test_manual_reconciliation_closes_only_confirmed_matching_attempt(self):
        from .stage2 import LIVE_KEY, reconcile_manual_submission
        from .models import PreparationAttempt
        _, approval = self.live_prepared()
        old_id = uuid.uuid4()
        claim_job(self.agent, old_id, [LIVE_KEY])
        args = dict(actor=self.actor, approval_id=approval.pk, expected_attempt_id=old_id,
                    confirmed_submitted=True, evidence_note='Operator saw Submit Successful after manual completion.')
        for overrides in [{'expected_attempt_id': uuid.uuid4()}, {'evidence_note': ''}, {'confirmed_submitted': False}]:
            with self.assertRaises(ValidationError):
                reconcile_manual_submission(**(args | overrides))
        reconcile_manual_submission(**args)
        reconcile_manual_submission(**args)
        old = PreparationAttempt.objects.get(pk=old_id)
        self.assertEqual(old.state, 'ABANDONED')
        self.assertIsNone(old.execution_slot)
        approval.refresh_from_db()
        self.assertEqual(approval.state, 'MANUALLY_SUBMITTED_UNVERIFIED')
        self.assertEqual(approval.attempt_id, old_id)
        self.assertFalse(approval.success_screenshot)
        replay = payload(claim_job(self.agent, old_id, [LIVE_KEY]))
        self.assertEqual(replay['Status'], 'MANUALLY_SUBMITTED_UNVERIFIED')
        self.assertIsNone(claim_job(self.agent, uuid.uuid4(), [LIVE_KEY]))

    def test_lookup_retry_preserves_failed_attempt_and_existing_approval(self):
        from .stage2 import LIVE_KEY, retry_saved_return_lookup
        from .models import PreparationAttempt
        _, approval = self.live_prepared()
        old_id = uuid.uuid4()
        data = payload(claim_job(self.agent, old_id, [LIVE_KEY]))
        report = self.client.post(data['ResultUrl'], json.dumps({'lease_token': data['LeaseToken'],
            'SubmissionStatus': 'SAVED_RETURN_ROW_NOT_FOUND'}), content_type='application/json')
        self.assertEqual(report.status_code, 200)
        args = dict(actor=self.actor, approval_id=approval.pk, expected_attempt_id=old_id,
                    evidence_note='OCR corrected and tested; only row selection was tested.')
        for overrides in [{'expected_attempt_id': uuid.uuid4()}, {'evidence_note': ''}]:
            with self.assertRaises(ValidationError):
                retry_saved_return_lookup(**(args | overrides))
        approval.refresh_from_db()
        approval.success_screenshot = 'evidence.png'
        approval.save(_service_write=True)
        with self.assertRaises(ValidationError):
            retry_saved_return_lookup(**args)
        approval.success_screenshot = ''
        approval.save(_service_write=True)
        retry_saved_return_lookup(**args)
        self.assertEqual(PreparationAttempt.objects.get(pk=old_id).state, 'FAILED')
        approval.refresh_from_db()
        self.assertEqual(approval.state, 'QUEUED')
        self.assertIsNone(approval.attempt_id)
        self.assertIn(str(old_id), approval.comment)
        with self.assertRaises(ValidationError):
            retry_saved_return_lookup(**args)
        new = claim_job(self.agent, uuid.uuid4(), [LIVE_KEY])
        self.assertEqual(new.pk, approval.pk)
        self.assertNotEqual(new.attempt_id, old_id)

    def test_live_unconfirmed_is_terminal_and_never_requeued(self):
        from .stage2 import LIVE_KEY
        order, approval=self.live_prepared()
        request_id=uuid.uuid4()
        data=payload(claim_job(self.agent, request_id, [LIVE_KEY]))
        report=self.client.post(data['ResultUrl'], json.dumps({'lease_token':data['LeaseToken'],
            'SubmissionStatus':'SUBMISSION_UNCONFIRMED'}),content_type='application/json')
        self.assertEqual(report.status_code,200)
        from .stage2 import retry_saved_return_lookup
        with self.assertRaises(ValidationError):
            retry_saved_return_lookup(actor=self.actor, approval_id=approval.pk,
                expected_attempt_id=request_id, evidence_note='OCR corrected')
        self.assertIsNone(claim_job(self.agent, uuid.uuid4(), [LIVE_KEY]))
        self.assertEqual(payload(claim_job(self.agent, request_id, [LIVE_KEY]))['State'],'FAILED')

    def test_dashboard_requires_submission_confirmation(self):
        job=self.job(); self.upload(job); self.result(job)
        order=WorkOrder.objects.get()
        browser=Client(); browser.force_login(self.actor)
        data={'version':order.version,'pdf_sha256':order.prepared_pdf_sha256}
        url=reverse('workorders:approve-stage2',args=[order.pk])
        self.assertEqual(browser.post(url,data).status_code,400)
        self.assertFalse(Stage2Approval.objects.exists())
        data['authorize_submission']='on'
        self.assertEqual(browser.post(url,data).status_code,302)
        self.assertTrue(Stage2Approval.objects.get().submission_enabled)

    def test_live_evidence_rejects_other_worker_and_bad_hash(self):
        import base64, hashlib
        from .stage2 import LIVE_KEY
        order, approval=self.live_prepared()
        data=payload(claim_job(self.agent, uuid.uuid4(), [LIVE_KEY]))
        image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        headers={'HTTP_X_LEASE_TOKEN':data['LeaseToken'], 'HTTP_X_SCREENSHOT_SHA256':hashlib.sha256(image).hexdigest()}
        other=Client(HTTP_AUTHORIZATION='Bearer '+self.other_token)
        self.assertEqual(other.put(data['ScreenshotUploadUrl'],image,content_type='image/png',**headers).status_code,403)
        headers['HTTP_X_SCREENSHOT_SHA256']='0'*64
        self.assertEqual(self.client.put(data['ScreenshotUploadUrl'],image,content_type='image/png',**headers).status_code,400)
        approval.refresh_from_db()
        self.assertFalse(approval.success_screenshot)

    def test_manual_submission_is_not_queued_or_authorized(self):
        from .stage2 import record_manual_submission, LIVE_KEY
        job=self.job(); self.upload(job); self.result(job)
        order=WorkOrder.objects.get()
        receipt=record_manual_submission(actor=self.actor, order_id=order.pk, version=order.version,
            evidence_note='Operator supplied a success screenshot; confirmation unverified.')
        self.assertFalse(receipt.submission_enabled)
        self.assertIsNone(receipt.attempt_id)
        self.assertIsNone(claim_job(self.agent, uuid.uuid4(), [LIVE_KEY]))
        self.assertIsNone(claim_job(self.agent, uuid.uuid4()))
        with self.assertRaises(ValidationError):
            approve(actor=self.actor,order_id=order.pk,version=order.version,
                    digest=order.prepared_pdf_sha256,submission_enabled=True)
        browser=Client(); browser.force_login(self.actor)
        response=browser.get(reverse('workorders:detail',args=[order.pk]))
        self.assertContains(response,'Manually submitted - BIR confirmation unverified')
        self.assertNotContains(response,'name="authorize_submission"')
