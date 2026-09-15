"""Opt-in fake demo work orders. Never overwrite an existing record or create credentials."""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from workorders.models import WorkOrder, Client, ClientFilingProfile, FormDefinition
from workorders.catalog_services import create_record
from workorders.services import create_work_order, transition_work_order


class Command(BaseCommand):
    help = "Create three clearly FAKE 2551Q demo work orders using an existing authorized user."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True, help="Username of an existing user with work-order add/change permission.")

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        try:
            actor = User.objects.get(**{User.USERNAME_FIELD: options["actor"]})
        except User.DoesNotExist as error:
            raise CommandError("The specified user does not exist.") from error
        created = 0
        try:
            for index, client in enumerate(("FAKE DEMO ALPHA", "FAKE DEMO BRAVO", "FAKE DEMO CHARLIE"), start=1):
                reference = f"DEMO-2551Q-{index:02}"
                if WorkOrder.objects.filter(legacy_client_reference=reference).exists():
                    continue
                if Client.objects.filter(client_code=reference).exists():
                    raise CommandError("A demo client code already exists without its demo work order. Review it manually.")
                taxpayer = create_record(model=Client, actor=actor, data={
                    "client_code": reference, "client_type": "NON_INDIVIDUAL", "registered_name": client,
                    "tin1": "000", "tin2": "000", "tin3": f"{index:03}", "tin4": "00000",
                    "rdo_code": "53A", "registered_address": "FAKE ADDRESS - DEMONSTRATION ONLY",
                    "zip_code": "0000", "telephone_number": "00000000000",
                    "email_address": f"demo{index}@example.invalid", "line_of_business": "TEST ONLY",
                })
                profile = create_record(model=ClientFilingProfile, actor=actor, data={"client": taxpayer,
                    "form_definition": FormDefinition.objects.get(definition_key="2551qv2018_zero")})
                order = create_work_order(actor=actor, client_filing_profile_id=profile.pk, data={
                    "filing_year": "2026", "filing_quarter": index, "form_data": {"atc_code": "PT 010"}, "zero_filing": True,
                    "zero_filing_approved": index == 2,
                })
                if index == 2:
                    transition_work_order(work_order_id=order.pk, actor=actor, expected_version=order.version,
                                          target=WorkOrder.Status.READY_TO_PREPARE)
                created += 1
        except (PermissionDenied, ValidationError) as error:
            raise CommandError("Demo creation failed. Check the actor's active status and work-order permissions.") from error
        self.stdout.write(self.style.SUCCESS(f"Created {created} fake demo work orders; existing demo references were left unchanged."))
