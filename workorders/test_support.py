"""Explicitly fake fixtures; never used by application services."""
import uuid
from .catalog_services import create_record
from .models import Client, ClientFilingProfile, FormDefinition
from .services import create_work_order


def fake_client_data(**changes):
    data = dict(client_code='TEST-' + uuid.uuid4().hex[:12], client_type='NON_INDIVIDUAL',
        registered_name='FAKE TEST CLIENT', trade_name='', tin1='001', tin2='002', tin3='003', tin4='00000',
        rdo_code='047', registered_address='FAKE ADDRESS', zip_code='0001', telephone_number='00000000000',
        email_address='fake@example.invalid', line_of_business='TEST ONLY')
    data.update(changes)
    return data


def make_profile(actor, *, key='2551qv2018_zero', client_data=None, **profile_data):
    taxpayer = create_record(model=Client, actor=actor, data=fake_client_data(**(client_data or {})))
    return create_record(model=ClientFilingProfile, actor=actor, data=dict(client=taxpayer,
        form_definition=FormDefinition.objects.get(definition_key=key), **profile_data))


def order_data(**changes):
    data = dict(filing_year='2026', filing_quarter=3, zero_filing=True, form_data={'atc_code': 'PT 010'})
    data.update(changes)
    return data


def fake_data(**changes):
    data = dict(client_name='FAKE TEST CLIENT', filing_year='2026', filing_quarter=3, atc_code='PT 010', zero_filing=True)
    data.update(changes)
    return data


def legacy_test_fixture_order(*, actor, data):
    client_fields = set(fake_client_data()) | {'client_name', 'client_id'}
    source = {name: value for name, value in data.items() if name in client_fields}
    source['trade_name'] = source.pop('client_name', 'FAKE TEST CLIENT')
    if 'client_id' in source:
        source['client_code'] = source.pop('client_id')
    profile = make_profile(actor, client_data=source)
    filing = {name: value for name, value in data.items() if name not in client_fields and name != 'atc_code'}
    filing['form_data'] = {'atc_code': data['atc_code']} if 'atc_code' in data else {}
    return create_work_order(actor=actor, client_filing_profile_id=profile.pk, data=filing)


def ensure_transactional_form(actor):
    """TransactionTestCase flushes migration seed data between classes."""
    if not FormDefinition.objects.filter(definition_key='2551qv2018_zero').exists():
        from .definitions import FORM_2551Q
        create_record(model=FormDefinition,actor=actor,data=dict(
            definition_key=FORM_2551Q.key,form_code=FORM_2551Q.form_code,form_version=FORM_2551Q.form_version,
            expected_form_number=FORM_2551Q.expected_form_number,display_name='Quarterly Percentage Tax Return',
            form_selection_text=FORM_2551Q.form_selection_text,filing_frequency=FORM_2551Q.filing_frequency,
            automation_key=FORM_2551Q.automation_key,preparation_automation_available=True))
