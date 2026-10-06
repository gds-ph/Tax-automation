from datetime import timedelta
from django.utils import timezone
from automation_api.models import Agent, PreparationAttempt


def describe(agent, attempt, now):
    online = bool(agent.is_active and agent.last_seen_at and agent.last_seen_at >= now - timedelta(minutes=2))
    connection = 'Disabled' if not agent.is_active else ('Online' if online else 'No recent heartbeat')
    activity = 'Idle' if online else 'Activity unknown'
    if attempt:
        approval = getattr(attempt, 'stage2_approval', None)
        activity = ('Submitting' if approval.submission_enabled else 'Validating') if approval else 'Preparing'
        if attempt.lease_expires_at <= now:
            activity = 'Needs review — task lease expired'
        elif not online:
            activity = 'Task claimed — progress unconfirmed'
    return {'agent': agent, 'attempt': attempt, 'connection': connection, 'online': online, 'activity': activity}


def workers():
    now = timezone.now()
    active = {a.agent_id: a for a in PreparationAttempt.objects.filter(
        state='RUNNING', execution_slot=1).select_related('work_order', 'stage2_approval')}
    return [describe(agent, active.get(agent.pk), now) for agent in Agent.objects.order_by('name')]
