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
        actor=get_user_model().objects.create_superuser(username='fake_bridge_admin',password='fake-only')
        ensure_transactional_form(actor)
        profile=make_profile(actor)
        order=create_work_order(actor=actor,client_filing_profile_id=profile.pk,data=order_data(zero_filing_approved=True))
        order=transition_work_order(work_order_id=order.pk,actor=actor,expected_version=1,target='READY_TO_PREPARE')
        _,token=create_agent(actor=actor,name='FAKE-POWERSHELL-BRIDGE')
        with tempfile.TemporaryDirectory(prefix='ebir-bridge-test-') as temporary:
            root=Path(temporary)
            config=root/'worker.json'
            config.write_text(json.dumps({'ApiBaseUrl':self.live_server_url,'Token':token,'AgentName':'FAKE-POWERSHELL-BRIDGE'}),encoding='utf-8')
            script=Path(__file__).resolve().parents[1]/'worker'/'WorkerBridge.ps1'
            def bridge(action, prefix=''):
                env=os.environ.copy();env.update(EBIR_BRIDGE_SCRIPT=str(script),EBIR_BRIDGE_CONFIG=str(config),EBIR_BRIDGE_ACTION=action)
                command="& ([scriptblock]::Create([IO.File]::ReadAllText($env:EBIR_BRIDGE_SCRIPT))) -Action $env:EBIR_BRIDGE_ACTION -ConfigPath $env:EBIR_BRIDGE_CONFIG; Write-Output 'BRIDGE_CALLER_CONTINUED'"
                result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',prefix+command],env=env,
                    capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertNotIn(token,result.stdout)
                output=result.stdout.rstrip()
                self.assertTrue(output.endswith('BRIDGE_CALLER_CONTINUED'),
                    'The bridge terminated its caller instead of returning: '+output)
                return json.loads(output.removesuffix('BRIDGE_CALLER_CONTINUED').rstrip())
            with override_settings(MEDIA_ROOT=root/'media'),patch('automation_api.worker_services.VM_WORKING_ROOT',str(root/'vm-working')),patch('automation_api.worker_services.VM_XML_ROOT',str(root/'vm-xml')):
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
                pdf.write_bytes(two_page_pdf())
                (root/'result.json').write_text(json.dumps({'AttemptId':job['AttemptId'],'PreparationStatusOutput':'AWAITING_SUBMISSION_APPROVAL',
                    'PreparedPdfPath':str(pdf),'SavedXmlPath':str(xml)}),encoding='utf-8')
                result=bridge('Publish');self.assertEqual(result['Status'],'AWAITING_SUBMISSION_APPROVAL')
                self.assertTrue(bridge('Publish')['Recorded'])
                self.assertFalse(bridge('Poll')['HasTask'])
                order.refresh_from_db();self.assertEqual(order.status,'AWAITING_SUBMISSION_APPROVAL')
                self.assertTrue((root/'media'/order.prepared_pdf.name).exists())

                from automation_api.stage2 import approve
                approve(actor=actor, order_id=order.pk, version=order.version, digest=order.prepared_pdf_sha256)
                script=script.with_name('Stage2Bridge.ps1')
                stage2=bridge('Poll')
                self.assertEqual(stage2['AutomationKey'], 'REVALIDATE_2551QV2018')
                self.assertTrue(bridge('Start')['Started'])
                self.assertTrue(bridge('Poll')['RecoveryRequired'])
                (root/'stage2-result.json').write_text(json.dumps({'AttemptId':stage2['AttemptId'],
                    'SubmissionStatus':'APPROVED_READY_TO_SUBMIT'}),encoding='utf-8')
                self.assertEqual(bridge('Publish')['Status'], 'APPROVED_READY_TO_SUBMIT')
                self.assertFalse(bridge('Poll')['HasTask'])
