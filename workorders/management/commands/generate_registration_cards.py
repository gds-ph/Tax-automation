from django.core.management.base import BaseCommand
from workorders import client_directory as directory
from workorders.models import RegistrationCardScan, RegistrationSetup
from workorders.registration_cards import scan_company


class Command(BaseCommand):
    help = 'Generate durable registration cards ahead of company visits. Safe to resume.'

    def add_arguments(self, parser):
        parser.add_argument('--company')
        parser.add_argument('--refresh', action='store_true')

    def handle(self, *args, **options):
        from audit.operational import record
        counts={'ready':0,'empty':0,'errors':0,'total':0}
        try:
            names = [options['company']] if options['company'] else directory.names()
        except Exception:
            record('background_failed', route='generate_registration_cards', level='ERROR')
            raise
        linked = set(RegistrationSetup.objects.values_list('folder', flat=True))
        names = [name for name in names if name not in linked]
        RegistrationCardScan.objects.bulk_create(
            [RegistrationCardScan(folder=name) for name in names], ignore_conflicts=True)
        for i, name in enumerate(names, 1):
            scan = scan_company(name, refresh=options['refresh'])
            counts['total'] += 1
            key={'READY':'ready','EMPTY':'empty'}.get(scan.status,'errors')
            counts[key] += 1
            self.stdout.write(f'{i}/{len(names)} {scan.status}')
            self.stdout.flush()
        record('cor_scan', level='WARNING' if counts['errors'] else 'INFO', counts=counts)
