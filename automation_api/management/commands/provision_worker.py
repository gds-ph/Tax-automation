"""Provision one local credential file, never print the bearer token."""
import json
from pathlib import Path
from urllib.parse import urlparse
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from automation_api.services import create_agent


class Command(BaseCommand):
    help='Create an agent and write its credential into an ignored secrets file.'

    def add_arguments(self,parser):
        parser.add_argument('--actor',required=True)
        parser.add_argument('--name',required=True)
        parser.add_argument('--token-file',required=True)
        parser.add_argument('--base-url',default='http://127.0.0.1:8001')

    def handle(self,*args,**options):
        root=(Path(settings.BASE_DIR)/'secrets').resolve()
        destination=Path(options['token_file']).resolve()
        if not destination.is_relative_to(root) or destination==root:
            raise CommandError('The credential file must be inside this workspace\'s ignored secrets directory.')
        url=urlparse(options['base_url'])
        if url.username or url.password or url.query or url.fragment or url.path not in ('','/') or not url.hostname:
            raise CommandError('Supply a base URL without a path, credentials, query or fragment.')
        if url.scheme!='https' and not (url.scheme=='http' and url.hostname in ('127.0.0.1','localhost')):
            raise CommandError('Use HTTPS for a VM connection; HTTP is allowed only for local tests.')
        User=get_user_model()
        try: actor=User.objects.get(**{User.USERNAME_FIELD:options['actor']})
        except User.DoesNotExist: raise CommandError('Actor not found.') from None
        destination.parent.mkdir(parents=True,exist_ok=True)
        created=False
        try:
            with transaction.atomic():
                agent,token=create_agent(actor=actor,name=options['name'])
                with destination.open('x',encoding='utf-8') as output:
                    created=True
                    json.dump({'ApiBaseUrl':options['base_url'].rstrip('/'),'AgentName':agent.name,'Token':token},output,indent=2)
        except Exception as error:
            if created: destination.unlink(missing_ok=True)
            raise CommandError('Provisioning failed. Check actor permissions, agent name uniqueness and that the output file does not already exist.') from None
        self.stdout.write(self.style.SUCCESS('Worker provisioned. Credential saved to the requested secrets file; token not printed.'))
