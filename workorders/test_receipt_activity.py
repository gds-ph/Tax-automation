from types import SimpleNamespace
from django.test import SimpleTestCase
from django.utils import timezone
from .receipt_activity import receipt_activity

class ReceiptActivityTests(SimpleTestCase):
    def receipt(self, archive):
        return SimpleNamespace(received_at=timezone.now(), finalized_at=timezone.now(),
            filename='return.xml', final_package='final_packages/return.pdf',
            evidence={'client_archive': archive})

    def test_saved_archive_shows_destination_and_timestamp(self):
        at = timezone.now()
        rows = receipt_activity(self.receipt({'status': 'saved', 'path': 'Company/2026',
            'filename': 'final.pdf', 'saved_at': at.isoformat()}))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2].created_at, at)
        self.assertIn('Company/2026', rows[2].description)
        self.assertIn('final.pdf', rows[2].description)

    def test_legacy_copy_time_is_explicit_and_failures_are_not_successes(self):
        rows = receipt_activity(self.receipt({'status': 'saved'}))
        self.assertIn('separate folder-copy time was not recorded', rows[2].description)
        for status in ['failed', 'not_configured']:
            rows = receipt_activity(self.receipt({'status': status}))
            self.assertNotIn('Final package saved to company folder', [r.get_kind_display for r in rows])
        self.assertEqual(receipt_activity(None), [])
