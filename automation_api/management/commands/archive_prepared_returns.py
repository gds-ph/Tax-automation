from django.core.management.base import BaseCommand
from automation_api.prepared_archive import enqueue, process_pending
from workorders.models import WorkOrder


class Command(BaseCommand):
    help = 'Copy verified prepared PDFs to their client folders; retry temporary failures.'

    def add_arguments(self, parser):
        parser.add_argument('--include-existing', action='store_true',
                            help='Also queue existing, unarchived, successfully prepared returns.')

    def handle(self, *args, **options):
        queued = 0
        if options['include_existing']:
            orders = WorkOrder.objects.filter(
                is_archived=False, prepared_return_archive__isnull=True,
                preparation_status_output='AWAITING_SUBMISSION_APPROVAL',
            ).exclude(prepared_pdf='').exclude(prepared_pdf_sha256='')
            for order in orders.iterator():
                enqueue(order)
                queued += 1
        saved = process_pending()
        self.stdout.write(f'Prepared returns queued: {queued}; saved: {saved}.')
