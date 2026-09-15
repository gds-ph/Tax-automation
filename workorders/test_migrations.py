"""Exercise forward migration against an isolated database, never the local app DB."""
import os
from pathlib import Path
import subprocess
import sys
from django.test import SimpleTestCase


class LegacyMigrationTests(SimpleTestCase):
    def test_legacy_values_audit_snapshots_and_explicit_link(self):
        script = r'''
import os, tempfile
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
from django.conf import settings
with tempfile.TemporaryDirectory(prefix='ebir-migration-test-') as temporary:
    settings.DATABASES['default']['NAME']=Path(temporary)/'migration.sqlite3'
    import django
    django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    executor=MigrationExecutor(connection)
    old_targets=[('workorders','0001_initial'),('audit','0001_initial'),('accounts','0001_dashboard_roles')]
    executor.migrate(old_targets)
    state=executor.loader.project_state(old_targets).apps
    User=state.get_model('auth','User')
    actor=User.objects.create(username='fake_migration_admin',is_staff=True,is_superuser=True,is_active=True)
    OldOrder=state.get_model('workorders','WorkOrder')
    old=OldOrder.objects.create(work_order_id='WO-FAKE-LEGACY',client_id='000-LEGACY',client_name='FAKE LEGACY',client_name_safe='FAKE_LEGACY',
        tin1='001',tin2='002',tin3='003',tin4='00000',rdo_code='53A',registered_name='FAKE LEGACY',registered_address='FAKE ADDRESS',
        zip_code='0001',telephone_number='00000',email_address='fake@example.invalid',line_of_business='TEST ONLY',
        form_code='2551Q',expected_form_number='2551Qv2018',form_selection_text='BIR Form 2551Qv2018',filing_year='2026',filing_quarter=3,
        year_end_month='12',calendar_year=True,atc_code='PT 010',zero_filing_approved=True,status='READY_TO_PREPARE',version=7,created_by_id=actor.pk)
    OldAudit=state.get_model('audit','AuditEvent')
    event=OldAudit.objects.create(work_order_id=old.pk,actor_id=actor.pk,kind='CREATED',new_status=old.status)
    original={f.attname:getattr(old,f.attname) for f in old._meta.concrete_fields}
    executor=MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    from workorders.models import WorkOrder,Client,ClientFilingProfile,FormDefinition
    from workorders.services import transition_work_order,link_legacy_work_order,get_preparation_automation_key
    from workorders.catalog_services import create_record
    from workorders.test_support import fake_client_data
    from audit.models import AuditEvent
    from django.contrib.auth import get_user_model
    from django.core.exceptions import ValidationError
    actor=get_user_model().objects.get(pk=actor.pk)
    migrated=WorkOrder.objects.get(pk=old.pk)
    for key,value in original.items():
        assert getattr(migrated,'legacy_client_reference' if key=='client_id' else key)==value, key
    assert Client.objects.count()==0
    assert migrated.client_id is None and migrated.client_filing_profile_id is None
    snap=migrated.current_snapshot
    assert snap.data['origin']=='legacy_m2_import'
    assert snap.data['legacy_columns']['legacy_client_reference']=='000-LEGACY'
    assert snap.created_by is None
    snap.full_clean()
    assert AuditEvent.objects.get(pk=event.pk).work_order_id==old.pk
    try:
        transition_work_order(work_order_id=old.pk,actor=actor,expected_version=7,target='READY_TO_PREPARE')
        raise AssertionError('legacy order queued')
    except ValidationError: pass
    try:
        get_preparation_automation_key(migrated)
        raise AssertionError('legacy order routed')
    except ValidationError: pass
    taxpayer=create_record(model=Client,actor=actor,data=fake_client_data(client_code='FAKE-EXPLICIT',client_type='INDIVIDUAL'))
    profile=create_record(model=ClientFilingProfile,actor=actor,data={'client':taxpayer,'form_definition':FormDefinition.objects.get(form_code='2551Q')})
    try:
        link_legacy_work_order(work_order_id=old.pk,actor=actor,expected_version=7,client_filing_profile_id=profile.pk,confirmed=False,form_data={'atc_code':'PT 010'})
        raise AssertionError('unconfirmed link')
    except ValidationError: pass
    linked=link_legacy_work_order(work_order_id=old.pk,actor=actor,expected_version=7,client_filing_profile_id=profile.pk,confirmed=True,form_data={'atc_code':'PT 010'})
    assert linked.status=='DRAFT' and linked.version==8 and not linked.zero_filing_approved
    assert linked.current_snapshot.revision==2 and linked.snapshots.get(revision=1).data==snap.data
    assert linked.client.client_type=='INDIVIDUAL'
    assert linked.audit_events.filter(kind='LEGACY_LINKED').count()==1
    connection.close()
print('Historical values, audit references, immutable import snapshot, and explicit linking verified.')
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
            env=os.environ.copy(), capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
