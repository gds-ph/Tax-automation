from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.core.paginator import Paginator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods
from django.contrib import messages
from django.conf import settings
from .models import SystemLog, AuditEvent, SystemSetting

@never_cache
@login_required
@require_GET
def logs(request):
    if not request.user.is_authenticated:
        raise PermissionDenied
    tab = 'activity' if request.GET.get('tab') == 'activity' else 'system'
    level = request.GET.get('level', '')
    if tab == 'activity':
        rows = AuditEvent.objects.select_related('actor','performed_by_agent','work_order').order_by('-created_at','-id')
    else:
        rows = SystemLog.objects.select_related('actor').all()
        if level in {'INFO','WARNING','ERROR'}:
            rows=rows.filter(level=level)
        else:
            level=''
    return render(request,'audit/logs.html',{'section':'logs','tab':tab,'level':level,
        'page_obj':Paginator(rows,50).get_page(request.GET.get('page'))})


@never_cache
@login_required
@require_http_methods(['GET', 'POST'])
def settings_page(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    current = SystemSetting.objects.filter(key='trrc_escalation_after_minutes').values_list('value', flat=True).first()
    if current is None:
        current = str(getattr(settings, 'TRRC_ESCALATION_AFTER_MINUTES', 0))
    interval = SystemSetting.objects.filter(key='receipt_check_interval_minutes').values_list('value', flat=True).first() or '1'
    from workorders.contact_defaults import DEFAULT_RDO_EMAIL
    saved_recipient = SystemSetting.objects.filter(key='trrc_escalation_recipient').values_list('value', flat=True).first()
    recipient = saved_recipient or DEFAULT_RDO_EMAIL
    active_recipient = saved_recipient or settings.TRRC_ESCALATION_RECIPIENT
    if request.method == 'POST':
        interval_raw = request.POST.get('receipt_minutes', '').strip()
        raw = request.POST.get('trrc_minutes', '').strip()
        recipient = request.POST.get('rdo_email', '').strip()
        try:
            validate_email(recipient)
            valid_email = len(recipient) <= 254
        except ValidationError:
            valid_email = False
        if not valid_email:
            messages.error(request, 'Enter a valid RDO email address.')
        elif not raw.isascii() or not raw.isdigit() or int(raw) < 0 or int(raw) > 43200:
            messages.error(request, 'Enter a duration from 0 to 43,200 minutes.')
        elif not interval_raw.isascii() or not interval_raw.isdigit() or not 1 <= int(interval_raw) <= 1440:
            messages.error(request, 'Enter an email-check interval from 1 to 1,440 minutes.')
        else:
            from django.db import transaction
            with transaction.atomic():
                SystemSetting.objects.update_or_create(key='trrc_escalation_recipient', defaults={'value': recipient})
                SystemSetting.objects.update_or_create(key='receipt_check_interval_minutes', defaults={'value': interval_raw})
                SystemSetting.objects.update_or_create(key='trrc_escalation_after_minutes', defaults={'value': raw})
            messages.success(request, 'Email check and TRRC escalation settings saved.')
            active_recipient = recipient
            current = raw
            interval = interval_raw
    return render(request, 'audit/settings.html', {'section': 'settings', 'trrc_minutes': current, 'receipt_minutes': interval,
        'rdo_email': recipient, 'trrc_recipient': active_recipient})
