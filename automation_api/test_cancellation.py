import hashlib
import json
import os
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import skipUnless
from django.test import SimpleTestCase
from .test_worker_api import WorkerApiTests
from .models import CancellationCleanup
from .stage2 import claim_job
from .worker_services import claim
from workorders.dashboard_actions import cancel_order
from workorders.models import WorkOrder


class CancellationTests(WorkerApiTests):
    def cancelled(self):
        job = self.job(); self.upload(job); self.result(job)
        order = WorkOrder.objects.get()
        cancel_order(actor=self.actor, work_order_id=order.pk, expected_version=order.version)
        return order, CancellationCleanup.objects.get()

    def poll(self, client=None):
        return (client or self.client).post('/api/agent/cancellation/claim/', '{}', content_type='application/json')

    def test_owner_replay_and_claim_exclusion(self):
        order, cleanup = self.cancelled()
        from django.test import Client
        other = Client(HTTP_AUTHORIZATION='Bearer '+self.other_token)
        self.assertEqual(self.poll(other).status_code, 204)
        self.assertIsNone(claim(agent=self.agent, request_id=uuid.uuid4(), automation_keys=['PREPARE_2551QV2018_ZERO']))
        self.assertIsNone(claim_job(self.agent, uuid.uuid4()))
        first = self.poll()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.poll().json(), first.json())
        self.assertEqual(first.json()['Source'], order.saved_xml_path)
        url = '/api/agent/cancellation/'+str(cleanup.pk)+'/result/'
        data = {'Archived': True, 'ArchivePath': first.json()['ArchivePath'], 'Sha256': 'a'*64, 'Error': ''}
        self.assertEqual(other.post(url, json.dumps(data), content_type='application/json').status_code, 404)
        self.assertEqual(self.client.post(url, json.dumps(data), content_type='application/json').status_code, 200)
        self.assertEqual(self.client.post(url, json.dumps(data), content_type='application/json').status_code, 200)
        cleanup.refresh_from_db(); self.assertEqual(cleanup.state, 'DONE')
        self.assertEqual(self.poll().status_code, 204)

    def test_conflicting_active_identity_is_not_moved(self):
        self.cancelled()
        self.make_order()
        self.assertEqual(self.poll().status_code, 204)
        cleanup = CancellationCleanup.objects.get()
        self.assertEqual(cleanup.state, 'FAILED')
        self.assertIn('Another active filing', cleanup.error)

    def test_running_desktop_blocks_cleanup(self):
        order, cleanup = self.cancelled()
        from unittest.mock import patch
        with patch('automation_api.cancellation.PreparationAttempt.objects.filter') as active:
            active.return_value.exists.return_value = True
            self.assertEqual(self.poll().status_code, 204)
        cleanup.refresh_from_db(); self.assertEqual(cleanup.state, 'PENDING')

    def test_invalid_destination_and_failure_reporting(self):
        order, cleanup = self.cancelled(); self.poll()
        url = '/api/agent/cancellation/'+str(cleanup.pk)+'/result/'
        data = {'Archived': True, 'ArchivePath': 'C:\\wrong.xml', 'Sha256': 'a'*64, 'Error': ''}
        self.assertEqual(self.client.post(url, json.dumps(data), content_type='application/json').status_code, 409)
        data['Archived'] = False
        self.assertEqual(self.client.post(url, json.dumps(data), content_type='application/json').status_code, 200)
        cleanup.refresh_from_db(); self.assertEqual(cleanup.state, 'FAILED')


@skipUnless(os.name == 'nt', 'Windows file locking and PowerShell integration')
class CancellationArchiveWindowsTests(SimpleTestCase):
    def exercise(self, scenario):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); save = root/'savefile'; save.mkdir()
            archive = root/'Cancelled'; source = save/'65070331200000-1601Cv2018-092026.xml'
            source.write_bytes(b'<return>test</return>')
            original = source.read_bytes()
            order = 'WO-2026-test'; destination = archive/order/source.name
            now = datetime.now(timezone.utc)
            job = {'CleanupId': str(uuid.uuid4()), 'WorkOrderId': order, 'Source': str(source),
                   'Filename': source.name, 'ArchivePath': str(destination),
                   'PreparedAfter': (now-timedelta(minutes=1)).isoformat(),
                   'CancelledAt': (now+timedelta(seconds=1)).isoformat()}
            if scenario == 'changed':
                job['CancelledAt'] = (now-timedelta(days=1)).isoformat()
            if scenario == 'collision':
                destination.parent.mkdir(parents=True); destination.write_bytes(b'unrelated')
            if scenario == 'outside':
                job['Source'] = str(root/'outside.xml')
                (root/'outside.xml').write_bytes(original)
            results = []
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args): pass
                def do_POST(self):
                    value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if self.path == '/api/agent/preparation/claim/':
                        self.send_response(204); self.end_headers(); return
                    if self.path.endswith('/claim/'):
                        payload = job
                    else:
                        results.append(value); payload = {'Recorded': True}
                    data = json.dumps(payload).encode()
                    self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data)))
                    self.end_headers(); self.wfile.write(data)
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                config = root/'worker.json'
                config.write_text(json.dumps({'ApiBaseUrl': f'http://127.0.0.1:{server.server_port}', 'Token': 'test-only'}))
                command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
                           str(Path('worker/Archive-CancelledReturn.ps1').resolve()),
                           '-ConfigPath', str(config), '-SaveFolder', str(save), '-ArchiveRoot', str(archive)]
                if scenario == 'bridge':
                    helper = Path('worker/Archive-CancelledReturn.ps1').read_text()
                    helper = helper.replace("'C:\\eBIRForms\\savefile'", "'"+str(save)+"'")
                    helper = helper.replace("'C:\\TaxAutomation\\Archive\\Cancelled'", "'"+str(archive)+"'")
                    (root/'Archive-CancelledReturn.ps1').write_text(helper)
                    (root/'WorkerBridge.ps1').write_bytes(Path('worker/WorkerBridge.ps1').read_bytes())
                    (root/'journal.json').write_text(json.dumps({'RequestId': str(uuid.uuid4()), 'Phase': 'Requesting', 'Claim': None, 'Result': None}))
                    command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
                               str(root/'WorkerBridge.ps1'), '-Action', 'Poll', '-ConfigPath', str(config)]
                output = subprocess.run(command, capture_output=True, text=True, timeout=30)
                self.assertEqual(output.returncode, 0, output.stderr)
                if scenario == 'bridge':
                    self.assertFalse(json.loads(output.stdout)['HasTask'])
                self.assertTrue(results, 'Cleanup did not run; close local mshta form windows for this test.')
                if scenario in ('success', 'bridge'):
                    self.assertTrue(results[-1]['Archived']); self.assertFalse(source.exists())
                    self.assertEqual(destination.read_bytes(), original)
                    self.assertEqual(results[-1]['Sha256'], hashlib.sha256(original).hexdigest())
                    replay = subprocess.run(command, capture_output=True, text=True, timeout=30)
                    self.assertEqual(replay.returncode, 0, replay.stderr)
                    self.assertTrue(results[-1]['Archived'])
                    source.write_bytes(b'new filing')
                    subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
                    self.assertFalse(results[-1]['Archived']); self.assertEqual(source.read_bytes(), b'new filing')
                else:
                    self.assertFalse(results[-1]['Archived']); self.assertEqual(source.read_bytes(), original)
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_archive_and_replay_without_deleting_replacement(self): self.exercise('success')
    def test_idle_parent_poll_runs_cleanup_without_json_noise(self): self.exercise('bridge')
    def test_changed_xml_is_retained(self): self.exercise('changed')
    def test_destination_collision_is_retained(self): self.exercise('collision')
    def test_outside_save_folder_is_retained(self): self.exercise('outside')
