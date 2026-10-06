"""Real HTTP smoke test of the Windows bridge against an isolated Django test server."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest import skipUnless
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import LiveServerTestCase,override_settings
from workorders.models import WorkOrder
from workorders.test_support import make_profile,order_data,ensure_transactional_form
from workorders.services import create_work_order,transition_work_order
from .services import create_agent
from .test_worker_api import two_page_pdf


@skipUnless(os.name=='nt','Windows PowerShell bridge integration test')
class WindowsBridgeTests(LiveServerTestCase):
    def test_poll_start_publish_and_crash_recovery_guard(self):
        self.exercise_bridge(False)

    def test_live_submission_evidence_and_replay(self):
        self.exercise_bridge(True)

    def test_automatic_archive_and_completed_replay(self):
        self.exercise_bridge(True, automatic=True)

    def test_monthly_automatic_archive_and_capabilities(self):
        self.exercise_bridge(True, automatic=True, monthly=True)

    def test_manual_reconciliation_releases_journal_only_after_server_review(self):
        self.exercise_bridge(True, monthly=True, manual=True)

    def test_eq_automatic_archive_and_capabilities(self):
        self.exercise_bridge(True, automatic=True, eq=True)

    def test_vat_withholding_archive_and_capabilities(self):
        self.exercise_bridge(True, automatic=True, vt=True)

    def test_final_withholding_archive_and_capabilities(self):
        self.exercise_bridge(True, automatic=True, final=True)

    def test_dashboard_release_clears_only_matching_running_journal(self):
        from .worker_services import abandon
        from workorders.services import retry_preparation
        actor = get_user_model().objects.create_superuser('recovery_operator')
        ensure_transactional_form(actor)
        profile = make_profile(actor)
        order = create_work_order(actor=actor, client_filing_profile_id=profile.pk,
                                  data=order_data(zero_filing_approved=True))
        order = transition_work_order(work_order_id=order.pk, actor=actor,
                                      expected_version=order.version, target='READY_TO_PREPARE')
        _, token = create_agent(actor=actor, name='recovery_vm')
        with tempfile.TemporaryDirectory(prefix='ebir-recovery-test-') as temporary:
            root = Path(temporary)
            config = root / 'worker.json'
            config.write_text(json.dumps({'ApiBaseUrl': self.live_server_url, 'Token': token}), encoding='utf-8')
            script = Path(__file__).resolve().parents[1] / 'worker' / 'WorkerBridge.ps1'
            def bridge(action):
                result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                    '-ExecutionPolicy', 'Bypass', '-File', str(script), '-ConfigPath', str(config),
                    '-Action', action], capture_output=True, text=True, timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn(token, result.stdout + result.stderr)
                return json.loads(result.stdout)
            with patch('automation_api.worker_services.VM_WORKING_ROOT', str(root / 'working')):
                job = bridge('Poll')
                self.assertTrue(bridge('Start')['Started'])
                journal = root / 'journal.json'
                original = journal.read_bytes()
                self.assertTrue(bridge('Poll')['RecoveryRequired'])
                self.assertEqual(journal.read_bytes(), original)
                order.refresh_from_db()
                abandon(actor=actor, attempt_id=job['AttemptId'], expected_version=order.version, confirmed_stopped=True)
                publishing = json.loads(original)
                publishing['Phase'] = 'Publishing'
                journal.write_text(json.dumps(publishing), encoding='utf-8')
                self.assertTrue(bridge('Poll')['RecoveryRequired'])
                self.assertEqual(json.loads(journal.read_text())['Phase'], 'Publishing')
                journal.write_bytes(original)
                order.refresh_from_db()
                retry_preparation(actor=actor, work_order_id=order.pk, expected_version=order.version)
                result = bridge('Poll')
                self.assertTrue(result['PendingCleared'])
                self.assertFalse(result['HasTask'])
                self.assertFalse(result['RecoveryRequired'])
                backups = list(root.glob('journal.json.released-*.bak'))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), original)
                self.assertEqual(json.loads(journal.read_text())['Phase'], 'Completed')
                next_job = bridge('Poll')
                self.assertTrue(next_job['HasTask'])
                self.assertNotEqual(next_job['AttemptId'], job['AttemptId'])

    def exercise_bridge(self, live, automatic=False, monthly=False, manual=False, eq=False, final=False, vt=False):
        actor=get_user_model().objects.create_superuser(username='fake_bridge_admin',password='fake-only')
        ensure_transactional_form(actor)
        if monthly:
            from workorders.models import FormDefinition
            from workorders.catalog_services import create_record
            if not FormDefinition.objects.filter(definition_key='1601cv2018_zero').exists():
                from dataclasses import asdict
                from workorders.definitions import FORM_1601C
                fields = asdict(FORM_1601C)
                fields['definition_key'] = fields.pop('key')
                create_record(model=FormDefinition, actor=actor, data={**fields,
                    'display_name': '1601C test', 'preparation_automation_available': True})
        if eq:
            from dataclasses import asdict
            from workorders.models import FormDefinition
            from workorders.catalog_services import create_record
            from workorders.definitions import FORM_1601EQ
            if not FormDefinition.objects.filter(definition_key=FORM_1601EQ.key).exists():
                fields=asdict(FORM_1601EQ)
                fields['definition_key']=fields.pop('key')
                create_record(model=FormDefinition, actor=actor, data={**fields,
                    'display_name':'1601EQ test','preparation_automation_available':True})
        if final or vt:
            from workorders.models import FormDefinition
            from workorders.catalog_services import create_record, update_record
            from workorders.definitions import FORM_0619F, FORM_1600VT
            if vt:
                FORM_0619F = FORM_1600VT
            from dataclasses import asdict
            form = FormDefinition.objects.filter(definition_key=FORM_0619F.key).first()
            if form is None:
                fields = asdict(FORM_0619F)
                fields['definition_key'] = fields.pop('key')
                create_record(model=FormDefinition, actor=actor, data={**fields, 'display_name': '0619F test', 'preparation_automation_available': True})
            else:
                update_record(model=FormDefinition, pk=form.pk, actor=actor, expected_version=form.version, changes={'preparation_automation_available': True})
        profile=make_profile(actor, key='1600vt_zero' if vt else '0619f_zero' if final else 'cor_1601eq' if eq else '1601cv2018_zero' if monthly else '2551qv2018_zero')
        data = order_data(zero_filing_approved=True)
        if monthly or final or vt:
            data.update(filing_month=1, filing_quarter=None, form_data={})
        if eq:
            data.update(form_data={})
        order=create_work_order(actor=actor,client_filing_profile_id=profile.pk,data=data)
        order=transition_work_order(work_order_id=order.pk,actor=actor,expected_version=1,target='READY_TO_PREPARE')
        _,token=create_agent(actor=actor,name='FAKE-POWERSHELL-BRIDGE')
        with tempfile.TemporaryDirectory(prefix='ebir-bridge-test-') as temporary:
            root=Path(temporary)
            config=root/'worker.json'
            configuration = {'ApiBaseUrl':self.live_server_url,'Token':token,'AgentName':'FAKE-POWERSHELL-BRIDGE'}
            if monthly:
                configuration.update(PreparationAutomationKeys=['PREPARE_1601CV2018_ZERO'], Stage2AutomationKeys=['SUBMIT_1601CV2018'])
            if eq:
                configuration.update(PreparationAutomationKeys=['PREPARE_1601EQ_ZERO'], Stage2AutomationKeys=['SUBMIT_1601EQ'])
            if final:
                configuration.update(PreparationAutomationKeys=['PREPARE_0619F_ZERO'], Stage2AutomationKeys=['SUBMIT_0619F'])
            if vt:
                configuration.update(PreparationAutomationKeys=['PREPARE_1600VT_ZERO'], Stage2AutomationKeys=['SUBMIT_1600VT'])
            config.write_text(json.dumps(configuration),encoding='utf-8')
            script=Path(__file__).resolve().parents[1]/'worker'/'WorkerBridge.ps1'
            def bridge(action, prefix='', fail=False):
                env=os.environ.copy();env.update(EBIR_BRIDGE_SCRIPT=str(script),EBIR_BRIDGE_CONFIG=str(config),EBIR_BRIDGE_ACTION=action)
                env.update(ARCHIVE_HELPER=str(script.with_name('Archive-SubmittedReturn.ps1')),
                           ARCHIVE_SAVE=str(root/'vm-xml'), ARCHIVE_ROOT=str(root/'archive'))
                extra = ' -ArchiveHelperPath $env:ARCHIVE_HELPER -SaveFolder $env:ARCHIVE_SAVE -ArchiveRoot $env:ARCHIVE_ROOT' if script.name=='Stage2Bridge.ps1' else ''
                command="$ErrorActionPreference='Stop'; & ([scriptblock]::Create([IO.File]::ReadAllText($env:EBIR_BRIDGE_SCRIPT))) -Action $env:EBIR_BRIDGE_ACTION -ConfigPath $env:EBIR_BRIDGE_CONFIG" + extra + "; Write-Output 'BRIDGE_CALLER_CONTINUED'"
                result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',prefix+command],env=env,
                    capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertNotIn(token,result.stdout+result.stderr)
                if fail:
                    self.assertNotEqual(result.returncode,0)
                    return
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertNotIn(token,result.stdout)
                output=result.stdout.rstrip()
                self.assertTrue(output.endswith('BRIDGE_CALLER_CONTINUED'),
                    'The bridge terminated its caller instead of returning: '+output)
                return json.loads(output.removesuffix('BRIDGE_CALLER_CONTINUED').rstrip())
            with override_settings(MEDIA_ROOT=root/'media', ENABLE_1601C_SUBMISSION=monthly, ENABLE_1601EQ_SUBMISSION=eq, ENABLE_0619F_SUBMISSION=final, ENABLE_1600VT_SUBMISSION=vt),patch('automation_api.worker_services.VM_WORKING_ROOT',str(root/'vm-working')),patch('automation_api.worker_services.VM_XML_ROOT',str(root/'vm-xml')):
                self.assertEqual(bridge('Health')['status'],'ok')
                timeout="function Invoke-WebRequest { throw [Net.WebException]::new('fake timeout', [Net.WebExceptionStatus]::Timeout) }; "
                transient=bridge('Poll',timeout)
                self.assertFalse(transient['HasTask'])
                self.assertFalse(transient['RecoveryRequired'])
                self.assertTrue(transient['Retryable'])
                pending=(root/'journal.json').read_bytes()
                self.assertTrue(bridge('Poll',timeout)['Retryable'])
                self.assertEqual((root/'journal.json').read_bytes(),pending)
                invalid="function Invoke-WebRequest { return [pscustomobject]@{ StatusCode=200; Content='invalid JSON' } }; "
                self.assertTrue(bridge('Poll',invalid)['RecoveryRequired'])
                self.assertEqual((root/'journal.json').read_bytes(),pending)
                job=bridge('Poll');self.assertTrue(job['HasTask']);self.assertNotIn('LeaseToken',job)
                same=bridge('Poll');self.assertEqual(same['AttemptId'],job['AttemptId'])
                self.assertTrue(bridge('Start')['Started'])
                self.assertTrue(bridge('Poll')['RecoveryRequired'])
                pdf=Path(job['ExpectedPdfPath']);xml=Path(job['ExpectedXmlPath'])
                xml.parent.mkdir(parents=True,exist_ok=True)
                xml.write_text('<FAKE_TEST_ONLY/>',encoding='utf-8')
                pdf.write_bytes(two_page_pdf(1 if eq or final or vt else 2))
                (root/'result.json').write_text(json.dumps({'AttemptId':job['AttemptId'],'PreparationStatusOutput':'AWAITING_SUBMISSION_APPROVAL',
                    'PreparedPdfPath':str(pdf),'SavedXmlPath':str(xml)}),encoding='utf-8')
                result=bridge('Publish');self.assertEqual(result['Status'],'AWAITING_SUBMISSION_APPROVAL')
                self.assertTrue(bridge('Publish')['Recorded'])
                self.assertFalse(bridge('Poll')['HasTask'])
                order.refresh_from_db();self.assertEqual(order.status,'AWAITING_SUBMISSION_APPROVAL')
                self.assertTrue((root/'media'/order.prepared_pdf.name).exists())

                from automation_api.stage2 import approve
                approve(actor=actor, order_id=order.pk, version=order.version, digest=order.prepared_pdf_sha256, submission_enabled=live)
                script=script.with_name('Stage2Bridge.ps1')
                stage2=bridge('Poll')
                self.assertEqual(stage2['AutomationKey'], 'SUBMIT_1600VT' if vt else 'SUBMIT_0619F' if final else 'SUBMIT_1601EQ' if eq else 'SUBMIT_1601CV2018' if monthly else ('SUBMIT_2551QV2018' if live else 'REVALIDATE_2551QV2018'))
                self.assertTrue(bridge('Start')['Started'])
                self.assertTrue(bridge('Poll')['RecoveryRequired'])
                status='SUBMITTED_WAITING_FOR_CONFIRMATION' if live else 'APPROVED_READY_TO_SUBMIT'
                if manual:
                    from .models import Stage2Approval
                    from .stage2 import reconcile_manual_submission
                    original_journal = (root/'stage2-journal.json').read_bytes()
                    bridge('Reconcile', fail=True)
                    self.assertEqual((root/'stage2-journal.json').read_bytes(), original_journal)
                    approval = Stage2Approval.objects.get(work_order=order)
                    reconcile_manual_submission(actor=actor, approval_id=approval.pk,
                        expected_attempt_id=stage2['AttemptId'], confirmed_submitted=True,
                        evidence_note='Fake test: operator completed manually.')
                    self.assertTrue(bridge('Reconcile')['Reconciled'])
                    backups = list(root.glob('stage2-manual-*.json'))
                    self.assertEqual(len(backups), 1)
                    self.assertEqual(backups[0].read_bytes(), original_journal)
                    self.assertTrue(xml.exists())
                    self.assertEqual(json.loads((root/'stage2-journal.json').read_text())['Phase'], 'Completed')
                    self.assertFalse(bridge('Poll')['HasTask'])
                    return
                outputs={'AttemptId':stage2['AttemptId'], 'SubmissionStatus':status}
                if live:
                    import base64
                    screenshot=Path(stage2['Inputs']['SuccessScreenshotPath'])
                    screenshot.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='))
                    outputs['SuccessScreenshotPath']=str(screenshot)
                (root/'stage2-result.json').write_text(json.dumps(outputs),encoding='utf-8')
                target = root/'archive'/order.work_order_id/xml.name
                original = xml.read_bytes()
                if live and not automatic:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b'conflicting archive')
                    bridge('Publish',fail=True)
                    self.assertEqual(json.loads((root/'stage2-journal.json').read_text())['Phase'],'ArchivePending')
                    self.assertTrue(bridge('Poll')['RecoveryRequired'])
                    bridge('Start',fail=True)
                    script=script.with_name('WorkerBridge.ps1')
                    self.assertTrue(bridge('Poll')['RecoveryRequired'])
                    script=script.with_name('Stage2Bridge.ps1')
                    self.assertTrue(xml.exists())
                    order.stage2_approval.refresh_from_db()
                    self.assertEqual(order.stage2_approval.state,status)
                    target.unlink()
                else:
                    published=bridge('Publish')
                    self.assertEqual(published['Status'],status)
                    self.assertTrue(bridge('Publish')['Recorded'])
                if live and automatic:
                    self.assertTrue(published['Archived'])
                    self.assertFalse(xml.exists())
                    self.assertEqual(target.read_bytes(),original)
                    self.assertTrue(bridge('Archive')['Archived'])
                if live and not automatic:
                    receipt = root/'submitted'/(stage2['AttemptId']+'.json')
                    self.assertTrue(receipt.exists())
                    archive_script = script.with_name('Archive-SubmittedReturn.ps1')
                    env = os.environ.copy()
                    env.update(ARCHIVE_SCRIPT=str(archive_script), ARCHIVE_CONFIG=str(config),
                               ARCHIVE_RECEIPT=str(receipt), ARCHIVE_SAVE=str(xml.parent),
                               ARCHIVE_ROOT=str(root/'archive'))
                    command = "& ([scriptblock]::Create([IO.File]::ReadAllText($env:ARCHIVE_SCRIPT))) -ConfigPath $env:ARCHIVE_CONFIG -ReceiptPath $env:ARCHIVE_RECEIPT -SaveFolder $env:ARCHIVE_SAVE -ArchiveRoot $env:ARCHIVE_ROOT"
                    def archive(commit=False, fail=False):
                        run = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
                                              command + (' -Commit' if commit else '')], env=env,
                                             capture_output=True,text=True,timeout=30,
                                             creationflags=subprocess.CREATE_NO_WINDOW)
                        self.assertNotIn(token, run.stdout + run.stderr)
                        if fail:
                            self.assertNotEqual(run.returncode, 0)
                            return
                        self.assertEqual(run.returncode,0,run.stderr)
                        return json.loads(run.stdout)
                    valid_receipt = receipt.read_bytes()
                    blocked_receipt = json.loads(valid_receipt)
                    blocked_receipt['Phase'] = 'Running'
                    receipt.write_text(json.dumps(blocked_receipt), encoding='utf-8')
                    archive(commit=True, fail=True)
                    self.assertTrue(xml.exists())
                    receipt.write_bytes(valid_receipt)
                    preview = archive()
                    self.assertEqual(preview['Mode'], 'Preview')
                    self.assertTrue(xml.exists())
                    target = Path(preview['ArchivePath'])
                    self.assertFalse(target.exists())
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b'conflicting archive')
                    archive(commit=True, fail=True)
                    self.assertTrue(xml.exists())
                    target.unlink()
                    original = xml.read_bytes()
                    # Resume archive only through the bridge; no desktop rerun.
                    self.assertTrue(bridge('Archive')['Archived'])
                    self.assertEqual(json.loads((root/'stage2-journal.json').read_text())['Phase'],'Completed')
                    self.assertFalse(xml.exists())
                    self.assertEqual(target.read_bytes(), original)
                    self.assertTrue(archive(commit=True)['Archived'])
                    # A recreated/changed working XML must not be silently removed.
                    xml.write_bytes(b'new working XML')
                    archive(commit=True, fail=True)
                    self.assertEqual(xml.read_bytes(), b'new working XML')
                if not live:
                    self.assertTrue(xml.exists())
                    self.assertFalse(target.exists())
                self.assertFalse(bridge('Poll')['HasTask'])
