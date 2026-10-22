import uuid
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from .models import ClientFilingProfile, QuarterlyWithholdingDraft
from .views import dashboard_permission
from .client_views import available
from .services import create_and_queue_work_order
from .quarterly_1601eq import normalize, totals, SCHEMA, AMOUNTS

SALT = '1601eq-supplier-queue-v1'


@dashboard_permission('workorders.view_client', 'workorders.view_clientfilingprofile',
                      'workorders.view_formdefinition', 'workorders.view_workorder',
                      'workorders.add_workorder', 'workorders.change_workorder')
@require_http_methods(['GET', 'POST'])
def prepare(request, pk, draft_pk):
    draft = get_object_or_404(QuarterlyWithholdingDraft, pk=draft_pk, client_id=pk)
    profile = get_object_or_404(ClientFilingProfile.objects.select_related('client', 'form_definition'),
                               client_id=pk, form_definition__definition_key='cor_1601eq')
    if not available(profile):
        return render(request, 'workorders/preparation_unavailable.html', {'taxpayer': profile.client}, status=409)
    versions = {'client': profile.client.version, 'form': profile.form_definition.version, 'profile': profile.version}
    error = ''
    status = 200
    schedule = None
    amount = None
    token = ''
    try:
        schedule = normalize(dict(schema=SCHEMA, rows=draft.data['rows'], quarter=draft.quarter, schedule_confirmed=True, **{k: draft.data.get(k, '0') for k in AMOUNTS},
                                  draft_id=str(draft.pk), draft_version=draft.version))
        amount = totals(schedule)
        if request.method == 'POST':
            if request.POST.get('reviewed') != 'on':
                raise ValidationError('Confirm the supplier schedule and return scope before queuing.')
            data = signing.loads(request.POST.get('preview_token', ''), salt=SALT, max_age=1800)
            if (data['actor'] != request.user.pk or data['profile'] != str(profile.pk) or
                data['versions'] != versions or data['draft'] != str(draft.pk) or
                data['draft_version'] != draft.version):
                raise ValidationError('The supplier schedule or client settings changed. Review again.')
            with transaction.atomic():
                locked = QuarterlyWithholdingDraft.objects.select_for_update().get(pk=draft.pk)
                if locked.version != data['draft_version'] or locked.data != draft.data:
                    raise ValidationError('The supplier schedule changed. Review again.')
                order = create_and_queue_work_order(actor=request.user, client_filing_profile_id=profile.pk,
                    request_id=uuid.UUID(data['request']), source_versions=versions,
                    data={'filing_year': str(locked.year), 'filing_quarter': locked.quarter,
                          'zero_filing': False, 'zero_filing_approved': False, 'form_data': schedule})
            return redirect('workorders:detail', pk=order.pk)
        token = signing.dumps({'actor': request.user.pk, 'profile': str(profile.pk), 'versions': versions,
            'draft': str(draft.pk), 'draft_version': draft.version, 'request': str(uuid.uuid4())}, salt=SALT)
    except (signing.BadSignature, KeyError, ValueError, TypeError):
        error = 'Review expired or invalid. Reload and review again.'
        status = 400
    except ValidationError as exc:
        error = ' '.join(exc.messages)
        status = 409
    template = 'workorders/quarterly_review_modal.html' if request.method == 'GET' and request.GET.get('modal') == '1' else 'workorders/quarterly_prepare.html'
    return render(request, template, {'taxpayer': profile.client, 'draft': draft,
        'profile': profile, 'schedule': schedule, 'amount': amount, 'preview_token': token, 'error': error, 'section': 'clients'}, status=status)
