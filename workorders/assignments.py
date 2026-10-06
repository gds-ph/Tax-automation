from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction

from audit.models import AuditEvent
from .models import WorkOrder
from .services import require_permission


class MemberChoice(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return user.get_full_name() or user.get_username()


class AssignmentForm(forms.Form):
    assigned_to = MemberChoice(queryset=None, required=False, empty_label='Unassigned', label='Assigned to', widget=forms.Select(attrs={'class': 'input'}))
    assignment_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        users = get_user_model().objects.filter(is_active=True).order_by('first_name', 'username')
        eligible = [u.pk for u in users if u.has_perm('workorders.view_workorder')]
        self.fields['assigned_to'].queryset = get_user_model().objects.filter(pk__in=eligible).order_by('first_name', 'username')


@transaction.atomic
def assign(*, actor, pk, assigned_to, assignment_version):
    require_permission(actor, 'workorders.change_workorder')
    order = WorkOrder.objects.select_for_update().get(pk=pk)
    if order.is_archived:
        raise ValidationError('Archived filings cannot be reassigned.')
    if order.assignment_version != assignment_version:
        raise ValidationError('The assignment changed. Reload and try again.')
    if assigned_to and (not assigned_to.is_active or not assigned_to.has_perm('workorders.view_workorder')):
        raise ValidationError('Choose an active team member with work-order access.')
    target = assigned_to.pk if assigned_to else None
    if order.assigned_to_id == target:
        return
    # Assignment is operational metadata: preserve the filing revision and approval.
    changed = models.QuerySet.update(
        WorkOrder.objects.filter(pk=pk, assignment_version=assignment_version),
        assigned_to_id=target, assignment_version=assignment_version + 1)
    if changed != 1:
        raise ValidationError('The assignment changed. Reload and try again.')
    AuditEvent.objects.create(work_order=order, actor=actor, kind='EDITED', changed_fields=['assigned_to'])
