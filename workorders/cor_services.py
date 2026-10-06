import hashlib
from django.core.exceptions import ValidationError
from django.db import transaction
from .catalog_services import create_record, require_permission
from .models import Client, ClientFilingProfile, FormDefinition, RegistrationSetup
from .cor_forms import TAXPAYER_FIELDS

FORM_KEYS = {'2551Q': '2551qv2018_zero', '1601C': '1601cv2018_zero', '0619F': '0619f_zero', '1600VT': '1600vt_zero', '1701Q': 'planned_1701q'}


@transaction.atomic
def save_setup(*, actor, draft, cleaned):
    require_permission(actor, 'workorders.add_client')
    require_permission(actor, 'workorders.add_clientfilingprofile')
    existing = RegistrationSetup.objects.filter(folder=draft['folder']).first()
    if existing:
        return existing.client
    if not cleaned.get('confirmed'):
        raise ValidationError('Review and confirmation are required.')
    fields = {k: cleaned[k] for k in TAXPAYER_FIELDS}
    if Client.objects.filter(**{k: fields[k] for k in ('tin1', 'tin2', 'tin3', 'tin4')}).exists():
        raise ValidationError('A client with this TIN and branch already exists. Review the existing client configuration instead of creating a duplicate.')
    fields['client_code'] = 'COR-' + hashlib.sha256(draft['folder'].encode()).hexdigest()[:24].upper()
    client = create_record(model=Client, actor=actor, data=fields)
    for code in cleaned['filings']:
        form = FormDefinition.objects.filter(definition_key=FORM_KEYS.get(code, 'cor_' + code.lower()), is_active=True).first()
        if form is None:
            raise ValidationError('This form is not configured in the catalog. Reload and review the selection.')
        create_record(model=ClientFilingProfile, actor=actor, data={
            'client': client, 'form_definition': form, 'calendar_or_fiscal': cleaned['calendar_or_fiscal'],
            'year_end_month': cleaned['year_end_month']})
    RegistrationSetup.objects.create(folder=draft['folder'], client=client, source_path=draft['path'],
        source_sha256=draft['sha256'], source_text=draft['transcript'], reviewed_forms=cleaned['filings'], reviewed_by=actor)
    return client
