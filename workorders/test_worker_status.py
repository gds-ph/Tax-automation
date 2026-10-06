from datetime import timedelta
from types import SimpleNamespace
from django.test import SimpleTestCase
from django.utils import timezone
from .worker_status import describe


class WorkerStatusTests(SimpleTestCase):
    def test_connection_and_claim_are_distinct(self):
        now = timezone.now()
        agent = SimpleNamespace(is_active=True, last_seen_at=now)
        attempt = SimpleNamespace(lease_expires_at=now + timedelta(minutes=10), stage2_approval=None)
        self.assertEqual(describe(agent, None, now)['activity'], 'Idle')
        self.assertEqual(describe(agent, attempt, now)['activity'], 'Preparing')
        attempt.stage2_approval = SimpleNamespace(submission_enabled=True)
        self.assertEqual(describe(agent, attempt, now)['activity'], 'Submitting')
        agent.last_seen_at = now - timedelta(minutes=5)
        self.assertEqual(describe(agent, attempt, now)['activity'], 'Task claimed — progress unconfirmed')
        attempt.lease_expires_at = now - timedelta(seconds=1)
        self.assertEqual(describe(agent, attempt, now)['activity'], 'Needs review — task lease expired')
        agent.is_active = False
        self.assertEqual(describe(agent, None, now)['connection'], 'Disabled')
