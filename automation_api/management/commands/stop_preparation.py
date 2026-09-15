from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand,CommandError
from automation_api.worker_services import abandon

class Command(BaseCommand):
    help='Release a preparation slot only after an operator confirms PAD has stopped. Never requeues automatically.'
    def add_arguments(self,parser):
        parser.add_argument('--actor',required=True)
        parser.add_argument('--attempt',required=True)
        parser.add_argument('--expected-version',required=True,type=int)
        parser.add_argument('--confirm-stopped',action='store_true')
    def handle(self,*args,**options):
        User=get_user_model()
        try:
            actor=User.objects.get(**{User.USERNAME_FIELD:options['actor']})
            order=abandon(actor=actor,attempt_id=options['attempt'],expected_version=options['expected_version'],confirmed_stopped=options['confirm_stopped'])
        except Exception:
            raise CommandError('Recovery rejected. Check permissions, attempt, version and explicit stopped confirmation.') from None
        self.stdout.write(self.style.SUCCESS(f'{order.work_order_id}: stopped attempt recorded; no rerun queued.'))
