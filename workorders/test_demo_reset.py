from django.contrib.auth import get_user_model
from django.test import TestCase, Client as BrowserClient
from django.urls import reverse
from .test_support import make_profile, order_data
from .services import create_work_order, transition_work_order
from .models import WorkOrder


class DemoResetTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(username='reset_admin', password='fake-only')
        self.profile = make_profile(self.actor, client_data={'client_code': 'DUMMY-CLIENT-001',
            'registered_name': 'ABC TEST COMPANY', 'tin1': '650', 'tin2': '703', 'tin3': '312', 'tin4': '00000'})
        self.order = create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk,
            data=order_data(zero_filing_approved=True))
        self.order = transition_work_order(actor=self.actor, work_order_id=self.order.pk,
            expected_version=self.order.version, target='READY_TO_PREPARE')
        self.url = reverse('workorders:reset-demo', args=[self.profile.client_id])
        self.client.force_login(self.actor)

    def data(self):
        response = self.client.get(self.url)
        return {'token': response.context['form']['token'].value(),
            'confirmed_stopped': 'on', 'confirmed_scope': 'on'}

    def test_get_is_read_only_and_post_downloads_scoped_script(self):
        other_year = create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk,
            data=order_data(filing_year='2025'))
        data = self.data()
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_archived)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        text = response.content.decode()
        self.assertIn(str(self.order.pk), text)
        self.assertNotIn(str(other_year.pk), text)
        self.assertIn('already completed', text)
        self.assertNotIn('Token', text)
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_archived)
        other_year.refresh_from_db()
        self.assertFalse(other_year.is_archived)
        self.assertEqual(WorkOrder.objects.count(), 2)

    def test_confirmation_required(self):
        data = self.data()
        del data['confirmed_stopped']
        self.client.post(self.url, data)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_archived)

    def test_monthly_reset_archives_only_monthly_tasks_and_exact_xml_names(self):
        from .models import ClientFilingProfile, FormDefinition
        from .catalog_services import create_record
        profile = create_record(model=ClientFilingProfile, actor=self.actor, data={
            'client': self.profile.client,
            'form_definition': FormDefinition.objects.get(definition_key='1601cv2018_zero')})
        monthly = create_work_order(actor=self.actor, client_filing_profile_id=profile.pk,
            data=dict(filing_year='2026', filing_month=2, zero_filing=True, form_data={}))
        other_year = create_work_order(actor=self.actor, client_filing_profile_id=profile.pk,
            data=dict(filing_year='2025', filing_month=2, zero_filing=True, form_data={}))
        page = self.client.get(self.url, {'form': '1601C'})
        self.assertContains(page, '1601C monthly reset')
        data = dict(token=page.context['form']['token'].value(), form_code='1601C',
                    confirmed_stopped='on', confirmed_scope='on')
        # A token for one form cannot reset another form.
        self.assertEqual(self.client.post(self.url, {**data, 'form_code': '2551Q'}).status_code, 409)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        script = response.content.decode()
        self.assertIn('65070331200000-1601Cv2018-012026.xml', script)
        self.assertIn('65070331200000-1601Cv2018-122026.xml', script)
        self.assertIn(monthly.work_order_id, script)
        self.assertNotIn(self.order.expected_xml_filename, script)
        self.assertNotIn(other_year.expected_xml_filename, script)
        self.assertIn('$preservePreparationJournal = $false', script)
        self.assertIn('Resolve the Stage 2 journal', script)
        monthly.refresh_from_db(); self.order.refresh_from_db(); other_year.refresh_from_db()
        self.assertTrue(monthly.is_archived)
        self.assertFalse(self.order.is_archived)
        self.assertFalse(other_year.is_archived)

    def test_monthly_reset_supports_manual_xml_without_dashboard_tasks(self):
        page = self.client.get(self.url, {'form': '1601C'})
        response = self.client.post(self.url, dict(token=page.context['form']['token'].value(),
            form_code='1601C', confirmed_stopped='on', confirmed_scope='on'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('65070331200000-1601Cv2018-082026.xml', response.content.decode())
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_archived)

    def test_stage2_cleanup_guard_allows_idle_poll_but_blocks_unresolved_states(self):
        import json
        import os
        import subprocess
        import tempfile
        from pathlib import Path
        from .demo_reset import cleanup_script
        if os.name != 'nt':
            self.skipTest('Windows PowerShell guard test')
        script = cleanup_script([self.order])
        guard = script[script.index('$stage2Path ='):script.index('$preservePreparationJournal =')]
        with tempfile.TemporaryDirectory() as folder:
            env = {**os.environ, 'RESET_GUARD_TEST_FOLDER': folder}
            for phase, claim, result, allowed in (
                ('Requesting', None, None, True), ('Completed', {}, {}, True),
                ('Requesting', {'AttemptId': 'test'}, None, False),
                ('Requesting', None, {'SubmissionStatus': 'test'}, False),
                ('Running', None, None, False), ('ArchivePending', {}, {}, False),
                ('ReadyToRun', {}, None, False), ('Publishing', {}, {}, False)):
                with self.subTest(phase=phase, claim=claim, result=result):
                    path = Path(folder) / 'stage2-journal.json'
                    path.write_text(json.dumps(dict(Phase=phase, Claim=claim, Result=result)), encoding='utf-8')
                    original = path.read_bytes()
                    run = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                        "$ErrorActionPreference='Stop'; $workerDir=$env:RESET_GUARD_TEST_FOLDER; " + guard],
                        env=env, capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertEqual(run.returncode == 0, allowed, run.stderr)
                    self.assertEqual(path.read_bytes(), original)

    def test_confirmed_reset_releases_running_attempt(self):
        from uuid import uuid4
        from automation_api.services import create_agent
        from automation_api.worker_services import claim
        agent, _ = create_agent(actor=self.actor, name='FAKE-RESET-WORKER')
        attempt = claim(agent=agent, request_id=uuid4(), automation_keys=['PREPARE_2551QV2018_ZERO'])
        response = self.client.post(self.url, self.data())
        self.assertEqual(response.status_code, 200)
        attempt.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(attempt.state, 'ABANDONED')
        self.assertIsNone(attempt.execution_slot)
        self.assertTrue(self.order.is_archived)

    def test_stale_confirmation_cannot_reset_new_job(self):
        data = self.data()
        create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk, data=order_data(filing_quarter=4))
        self.assertEqual(self.client.post(self.url, data).status_code, 409)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_archived)

    def test_csrf_and_authentication_required(self):
        browser = BrowserClient(enforce_csrf_checks=True)
        self.assertEqual(browser.get(self.url).status_code, 302)
        browser.force_login(self.actor)
        self.assertEqual(browser.post(self.url, self.data()).status_code, 403)

    def test_other_client_not_supported(self):
        other = make_profile(self.actor)
        self.assertEqual(self.client.get(reverse('workorders:reset-demo', args=[other.client_id])).status_code, 404)

    def test_new_test_company_reset_is_exactly_scoped(self):
        profile = make_profile(self.actor, client_data={
            'client_code': 'TEST-639848605-00000', 'registered_name': 'Test Company',
            'tin1': '639', 'tin2': '848', 'tin3': '605', 'tin4': '00000'})
        order = create_work_order(actor=self.actor, client_filing_profile_id=profile.pk,
                                  data=order_data(zero_filing_approved=True))
        url = reverse('workorders:reset-demo', args=[profile.client_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(self.client.get(reverse('workorders:client-detail', args=[profile.client_id])),
                            'Reset 2026 test filings')
        response = self.client.post(url, {'token': response.context['form']['token'].value(),
                                         'confirmed_stopped': 'on', 'confirmed_scope': 'on'})
        self.assertEqual(response.status_code,200)
        self.assertIn(order.expected_saved_return_name+'.xml', response.content.decode())
        self.assertNotIn('ABC_TEST_COMPANY', response.content.decode())
        self.assertNotIn(self.order.expected_saved_return_name+'.xml', response.content.decode())
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_archived)

    def test_reset_preserves_unresolved_stage2(self):
        from uuid import uuid4
        from datetime import timedelta
        from django.utils import timezone
        from automation_api.models import PreparationAttempt, Stage2Approval
        from automation_api.services import create_agent
        agent, _ = create_agent(actor=self.actor, name='STAGE2-RESET-TEST')
        attempt = PreparationAttempt(id=uuid4(), work_order=self.order, snapshot=self.order.current_snapshot,
                                     agent=agent, lease_expires_at=timezone.now()+timedelta(minutes=30))
        attempt.save(_service_write=True)
        approval = Stage2Approval(work_order=self.order, snapshot=self.order.current_snapshot,
                                  approved_by=self.actor, pdf_sha256='a'*64, submission_enabled=True,
                                  state='RUNNING', attempt=attempt)
        approval.save(_service_write=True)
        response = self.client.post(self.url, self.data())
        self.assertEqual(response.status_code,409)
        self.assertContains(response,'unresolved attempt',status_code=409)
        attempt.refresh_from_db(); approval.refresh_from_db(); self.order.refresh_from_db()
        self.assertEqual(attempt.state,'RUNNING')
        self.assertEqual(approval.state,'RUNNING')
        self.assertFalse(self.order.is_archived)

    def test_non_superuser_denied(self):
        from django.contrib.auth.models import Permission
        user = get_user_model().objects.create_user(username='operator', password='fake-only')
        user.user_permissions.add(*Permission.objects.filter(codename__in=['change_workorder', 'change_agent']))
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_updated_test_identity_shows_reset_and_scopes_new_tin(self):
        from .catalog_services import update_record
        from .models import Client
        from .demo_reset import cleanup_script
        taxpayer = self.profile.client
        update_record(model=Client, pk=taxpayer.pk, actor=self.actor, expected_version=taxpayer.version,
            changes={'registered_name': 'TEST AUTOMATION COMPANY - TEST ONLY',
                     'tin1': '639', 'tin2': '845', 'tin3': '602'})
        self.profile.refresh_from_db()
        new_order = create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk,
            data=order_data(filing_quarter=2))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertContains(self.client.get(reverse('workorders:client-detail', args=[taxpayer.pk])), 'Reset 2026 test filings')
        script = cleanup_script([self.order, new_order])
        self.assertIn(new_order.expected_saved_return_name + '.xml', script)
        self.assertIn(self.order.expected_saved_return_name + '.xml', script)
        self.assertNotIn('foreach ($quarter in 1..4)', script)
        new_order.refresh_from_db()
        self.assertFalse(new_order.is_archived)
