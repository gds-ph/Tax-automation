from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from django.test import Client

from workorders.models import WorkOrder
from workorders.client_directory import DirectoryUnavailable
from .models import PreparedReturnArchive
from .prepared_archive import copy_pdf, prepared_filename, process_pending
from .test_worker_api import WorkerApiTests
from .worker_services import private_pdf_path, WorkerError


class PreparedArchiveTests(TestCase):
    setUpTestData = classmethod(WorkerApiTests.setUpTestData.__func__)
    setUp = WorkerApiTests.setUp
    make_order = WorkerApiTests.make_order
    claim = WorkerApiTests.claim
    job = WorkerApiTests.job
    upload = WorkerApiTests.upload
    result = WorkerApiTests.result

    def prepared(self):
        job = self.job()
        self.upload(job)
        self.assertEqual(self.result(job).status_code, 200)
        return WorkOrder.objects.get(), job

    def test_success_queues_once_without_contacting_share(self):
        with patch('automation_api.prepared_archive.copy_pdf') as copy:
            order, job = self.prepared()
            self.result(job)
        copy.assert_not_called()
        self.assertEqual(PreparedReturnArchive.objects.count(), 1)
        self.assertEqual(order.prepared_return_archive.sha256, order.prepared_pdf_sha256)

    def test_failure_does_not_queue(self):
        job = self.job()
        self.result(job, PreparationStatusOutput='FAILED_SYSTEM', PreparedPdfPath='', SavedXmlPath='')
        self.assertFalse(PreparedReturnArchive.objects.exists())

    @patch('automation_api.prepared_archive.copy_pdf', return_value='Company/BIR/prepared.pdf')
    def test_background_copy_status_and_no_repeat(self, copy):
        order, _ = self.prepared()
        self.assertEqual(process_pending(), 1)
        self.assertEqual(process_pending(), 0)
        copy.assert_called_once()
        self.assertEqual(copy.call_args.args[1], private_pdf_path(order).read_bytes())
        browser = Client(); browser.force_login(self.actor)
        self.assertContains(browser.get(reverse('workorders:detail', args=[order.pk]) + '?tab=documents'),
                            'Company/BIR/prepared.pdf')

    @patch('automation_api.prepared_archive.copy_pdf', side_effect=DirectoryUnavailable('Offline'))
    def test_temporary_failure_retries_without_changing_filing(self, copy):
        order, _ = self.prepared()
        version = order.version
        self.assertEqual(process_pending(), 0)
        job = PreparedReturnArchive.objects.get()
        self.assertEqual(job.state, 'RETRY')
        self.assertGreater(job.next_attempt_at, timezone.now())
        process_pending(); self.assertEqual(copy.call_count, 1)
        PreparedReturnArchive.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now()-timedelta(seconds=1))
        copy.side_effect = None; copy.return_value = 'Company/BIR/prepared.pdf'
        self.assertEqual(process_pending(), 1)
        order.refresh_from_db()
        self.assertEqual(order.version, version)
        self.assertEqual(order.status, 'AWAITING_SUBMISSION_APPROVAL')

    @patch('automation_api.prepared_archive.copy_pdf')
    def test_corrupt_source_is_blocked(self, copy):
        order, _ = self.prepared()
        private_pdf_path(order).write_bytes(b'changed')
        process_pending()
        self.assertEqual(PreparedReturnArchive.objects.get().state, 'BLOCKED')
        copy.assert_not_called()

    @patch('automation_api.prepared_archive.directory.fetch')
    @patch('automation_api.prepared_archive.directory.upload_pdf')
    @patch('automation_api.prepared_archive.directory.read_json')
    @patch('automation_api.prepared_archive.directory.filing_folder', return_value='Company/BIR')
    def test_copy_and_lost_ack_replay_verify_content(self, folder, browse, upload, fetch):
        order, _ = self.prepared()
        data = private_pdf_path(order).read_bytes()
        filename = prepared_filename(order)
        self.assertNotEqual(filename, order.review_pdf_filename)
        browse.return_value = {'entries': []}
        upload.return_value = {'saved': [{'name': filename}]}
        fetch.return_value = data
        self.assertEqual(copy_pdf(order, data), 'Company/BIR/' + filename)
        folder.assert_called_with(order.client, order)
        upload.assert_called_once_with('Company/BIR', filename, data)
        browse.return_value = {'entries': [{'type': 'file', 'name': filename}]}
        copy_pdf(order, data)
        self.assertEqual(upload.call_count, 1)
        fetch.return_value = b'different'
        with self.assertRaises(WorkerError):
            copy_pdf(order, data)
        self.assertEqual(upload.call_count, 1)

    @patch('automation_api.prepared_archive.directory.filing_folder', return_value=None)
    def test_missing_mapping_stays_retryable(self, folder):
        order, _ = self.prepared()
        process_pending()
        self.assertEqual(PreparedReturnArchive.objects.get().state, 'RETRY')
