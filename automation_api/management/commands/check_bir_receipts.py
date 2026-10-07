from django.core.management.base import BaseCommand
from automation_api.receipts import poll_receipts


class Command(BaseCommand):
    help = 'Check due submitted filings for an exact receipt; retry every minute.'

    def handle(self, *args, **options):
        from automation_api.prepared_archive import process_pending
        from automation_api.screenshot_archive import process_pending as copy_screenshots
        from audit.operational import record
        from audit.models import SystemLog
        from django.utils import timezone
        from datetime import timedelta
        SystemLog.objects.filter(created_at__lt=timezone.now()-timedelta(days=30)).delete()
        try:
            process_pending()
        except Exception:
            record('background_failed', route='archive_prepared_returns', level='ERROR')
        try:
            copy_screenshots()
        except Exception:
            record('background_failed', route='archive_submission_screenshots', level='ERROR')
        try:
            checked, received, errors = poll_receipts()
        except Exception:
            record('background_failed', route='check_bir_receipts', level='ERROR')
            raise
        record('receipt_check', level='WARNING' if errors else 'INFO', counts={'checked':checked,'received':received,'errors':errors})
        self.stdout.write(f'Checked: {checked}; receipts found: {received}; errors: {errors}.')
