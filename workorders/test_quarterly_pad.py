import uuid
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from .test_support import make_profile
from .test_quarterly_withholding import row
from .quarterly_withholding import calculate
from .quarterly_1601eq import normalize, totals, SCHEMA
from .quarterly_models import QuarterlyWithholdingDraft
from .models import WorkOrder
from .services import validate_readiness
from .payroll_1601c import preparation_key

class QuarterlyPadTests(TestCase):
    def setUp(self):
        self.admin=get_user_model().objects.create_superuser('eq_pad_admin')
        self.profile=make_profile(self.admin,key='cor_1601eq')
        self.draft=QuarterlyWithholdingDraft.objects.create(client=self.profile.client,year=2026,quarter=3,data=calculate([row()],3,'100','200','10','20','30'))
        self.url=reverse('workorders:quarterly-prepare',args=[self.profile.client_id,self.draft.pk])
        self.client.force_login(self.admin)
    def test_queue_snapshot_and_idempotence(self):
        response=self.client.get(self.url)
        self.assertEqual(response.status_code,200)
        token=response.context['preview_token']
        self.assertEqual(self.client.post(self.url,{'preview_token':token}).status_code,409)
        response=self.client.post(self.url,{'preview_token':token,'reviewed':'on'})
        self.assertEqual(response.status_code,302)
        order=WorkOrder.objects.get()
        self.assertEqual(order.status,'READY_TO_PREPARE')
        self.assertEqual(validate_readiness(order),'PREPARE_1601EQ_SUPPLIERS')
        self.assertEqual(preparation_key(order.current_snapshot.data),'PREPARE_1601EQ_SUPPLIERS')
        self.assertEqual(order.form_data['surcharge'],'10.00')
        from automation_api.models import Agent
        from automation_api.worker_services import claim, payload
        from automation_api.services import create_agent
        agent, _ = create_agent(actor=self.admin, name='quarterly-pad-test')
        attempt=claim(agent=agent,request_id=uuid.uuid4(),automation_keys=['PREPARE_1601EQ_SUPPLIERS'])
        job=payload(attempt)
        self.assertEqual(job['Inputs']['QuarterlyTotals']['due'],'1760.00')
        self.assertEqual(job['Inputs']['QuarterlySchedule']['draft_version'],1)

        self.client.post(self.url,{'preview_token':token,'reviewed':'on'})
        self.assertEqual(WorkOrder.objects.count(),1)
        self.draft.data['surcharge']='999';self.draft.save()
        order.refresh_from_db();self.assertEqual(order.form_data['surcharge'],'10.00')
    def test_stale_revision_rejected(self):
        token=self.client.get(self.url).context['preview_token']
        self.draft.version+=1;self.draft.save()
        self.assertEqual(self.client.post(self.url,{'preview_token':token,'reviewed':'on'}).status_code,409)
        self.assertFalse(WorkOrder.objects.exists())
    def test_overpayment_fails_closed(self):
        data=dict(schema=SCHEMA,quarter=3,rows=[row()],schedule_confirmed=True,draft_id=str(self.draft.pk),draft_version=1)
        with self.assertRaises(ValidationError):normalize({**data,'first_remittance':'2001'})
        rounded = totals({**data,'rows':[{**row(),'base':'0.25'},{**row(),'base':'0.25'}]})
        self.assertEqual(rounded['transaction_withheld'], '0.02')
        self.assertEqual(rounded['withheld'], '0.01')
        self.assertEqual(rounded['rounding_adjustment'], '-0.01')
        with self.assertRaises(ValidationError):
            normalize({**data,'rows':[{**row(),'base':'0.25'},{**row(),'base':'0.25'}],'first_remittance':'0.02'})

    def test_rounding_review_and_queued_payload(self):
        rows=[{**row(),'atc':'WC850','base':base} for base in ['1095714','2191429','2191429','2272857']]
        self.draft.data=calculate(rows,3,surcharge='10000'); self.draft.save()
        response=self.client.get(self.url)
        self.assertContains(response,'Rounding adjustment for eBIRForms')
        self.assertEqual(response.context['amount']['rounding_adjustment'],'-0.02')
        self.assertEqual(response.context['amount']['due'],'48757.14')
        self.client.post(self.url,{'preview_token':response.context['preview_token'],'reviewed':'on'})
        order=WorkOrder.objects.get()
        result=totals(order.form_data)
        self.assertEqual(result['withheld'],'38757.14')
        self.assertEqual(result['rows'],self.draft.data['rows'])
        positive=totals({**order.form_data,'rows':[{**row(),'base':'0.24'},{**row(),'base':'1.24'}]})
        self.assertEqual(positive['rounding_adjustment'],'0.01')
