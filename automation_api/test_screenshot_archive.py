import base64
import hashlib
import json
import uuid
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from . import test_worker_api as fixtures
from .models import SubmissionScreenshotArchive
from .stage2 import approve, claim_job, payload, LIVE_KEY, SUCCESS, screenshot_path
from .screenshot_archive import process_pending, screenshot_filename
from workorders.models import WorkOrder
from workorders.client_directory import DirectoryUnavailable


class ScreenshotArchiveTests(TestCase):
    setUpTestData = classmethod(fixtures.WorkerApiTests.setUpTestData.__func__)
    setUp = fixtures.WorkerApiTests.setUp
    make_order = fixtures.WorkerApiTests.make_order
    claim = fixtures.WorkerApiTests.claim
    job = fixtures.WorkerApiTests.job
    upload = fixtures.WorkerApiTests.upload
    result = fixtures.WorkerApiTests.result

    def submitted(self, finish=True):
        job = self.job(); self.upload(job); self.result(job)
        order = WorkOrder.objects.get()
        approval = approve(actor=self.actor, order_id=order.pk, version=order.version,
                           digest=order.prepared_pdf_sha256, submission_enabled=True)
        data = payload(claim_job(self.agent, uuid.uuid4(), [LIVE_KEY]))
        image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        response = self.client.put(data['ScreenshotUploadUrl'], image, content_type='image/png',
            HTTP_X_LEASE_TOKEN=data['LeaseToken'], HTTP_X_SCREENSHOT_SHA256=hashlib.sha256(image).hexdigest())
        self.assertEqual(response.status_code, 200)
        if finish:
            response = self.client.post(data['ResultUrl'], json.dumps({
                'lease_token': data['LeaseToken'], 'SubmissionStatus': SUCCESS}), content_type='application/json')
            self.assertEqual(response.status_code, 200)
        approval.refresh_from_db()
        return order, approval, image

    @patch('automation_api.screenshot_archive.copy_pdf', return_value='Company/BIR/shot.png')
    def test_existing_success_is_copied_once_without_receipt(self, copy):
        order, approval, image = self.submitted()
        self.assertEqual(process_pending(), 1)
        copy.assert_called_once_with(order, image, filename=screenshot_filename(order), content_type='image/png')
        self.assertEqual(SubmissionScreenshotArchive.objects.get().state, 'SAVED')
        self.assertEqual(process_pending(), 0)
        self.assertEqual(copy.call_count, 1)

    @patch('automation_api.screenshot_archive.copy_pdf')
    def test_unreported_attempt_is_not_copied(self, copy):
        self.submitted(finish=False)
        process_pending()
        self.assertFalse(SubmissionScreenshotArchive.objects.exists())
        copy.assert_not_called()

    @patch('automation_api.screenshot_archive.copy_pdf')
    def test_changed_source_blocks_copy(self, copy):
        order, approval, image = self.submitted()
        screenshot_path(approval).write_bytes(b'changed')
        process_pending()
        self.assertEqual(SubmissionScreenshotArchive.objects.get().state, 'BLOCKED')
        copy.assert_not_called()

    @patch('automation_api.screenshot_archive.copy_pdf', side_effect=DirectoryUnavailable('Offline'))
    def test_share_failure_retries_and_preserves_submission(self, copy):
        order, approval, image = self.submitted()
        process_pending()
        job = SubmissionScreenshotArchive.objects.get()
        self.assertEqual(job.state, 'RETRY')
        self.assertGreater(job.next_attempt_at, timezone.now())
        approval.refresh_from_db(); self.assertEqual(approval.state, SUCCESS)
        process_pending(); self.assertEqual(copy.call_count, 1)
        job.next_attempt_at = timezone.now(); job.save()
        copy.side_effect = None; copy.return_value = 'Company/BIR/shot.png'
        self.assertEqual(process_pending(), 1)

    @patch('workorders.client_directory._write', return_value={'saved': [{'name': 'shot.png'}]})
    def test_png_upload_uses_image_content_type(self, write):
        from workorders.client_directory import upload_file
        from django.test import override_settings
        with override_settings(CLIENT_FILES_URL='http://localhost:3020'):
            upload_file('Company/BIR', 'shot.png', b'png', content_type='image/png')
        self.assertIn(b'Content-Type: image/png', write.call_args.args[0].data)
