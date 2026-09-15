import hashlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from audit.models import AuditEvent
from .models import Agent
from .services import create_agent, rotate_agent_token, disable_agent


class AgentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(username="agent_admin", password="test-only-password")

    def test_token_is_generated_and_only_hash_is_stored(self):
        agent, raw = create_agent(actor=self.actor, name="FAKE-VM")
        agent.refresh_from_db()
        self.assertGreaterEqual(len(raw), 80)
        self.assertEqual(agent.token_hash, hashlib.sha256(raw.encode()).hexdigest())
        self.assertNotEqual(agent.token_hash, raw)
        self.assertTrue(agent.check_token(raw))
        for wrong in ("", "incorrect", None, raw + "wrong"):
            self.assertFalse(agent.check_token(wrong))
        self.assertNotIn(raw, str(Agent.objects.values().get(pk=agent.pk)))
        self.assertNotIn(raw, str(list(AuditEvent.objects.values())))
        self.assertEqual(agent.audit_events.get().kind, "AGENT_CREATED")

    def test_rotation_revokes_old_token(self):
        agent, old = create_agent(actor=self.actor, name="FAKE-VM")
        rotated, new = rotate_agent_token(actor=self.actor, agent_id=agent.pk)
        self.assertNotEqual(old, new)
        self.assertFalse(rotated.check_token(old))
        self.assertTrue(rotated.check_token(new))
        self.assertEqual(rotated.audit_events.filter(kind="AGENT_TOKEN_ROTATED").count(), 1)

    def test_disabled_agent_rejects_token_and_rotation_does_not_reenable(self):
        agent, raw = create_agent(actor=self.actor, name="FAKE-VM")
        disabled = disable_agent(actor=self.actor, agent_id=agent.pk)
        self.assertFalse(disabled.check_token(raw))
        rotated, new = rotate_agent_token(actor=self.actor, agent_id=agent.pk)
        self.assertFalse(rotated.check_token(new))

    def test_agent_permissions(self):
        ordinary = get_user_model().objects.create_user(username="ordinary")
        agent, _ = create_agent(actor=self.actor, name="FAKE-VM")
        with self.assertRaises(PermissionDenied):
            create_agent(actor=ordinary, name="OTHER")
        with self.assertRaises(PermissionDenied):
            rotate_agent_token(actor=ordinary, agent_id=agent.pk)
        with self.assertRaises(PermissionDenied):
            disable_agent(actor=ordinary, agent_id=agent.pk)

    def test_audit_failure_rolls_back_agent_creation_and_rotation(self):
        with patch("automation_api.services.AuditEvent.objects.create", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                create_agent(actor=self.actor, name="FAKE-VM")
        self.assertEqual(Agent.objects.count(), 0)
        agent, old = create_agent(actor=self.actor, name="FAKE-VM")
        with patch("automation_api.services.AuditEvent.objects.create", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                rotate_agent_token(actor=self.actor, agent_id=agent.pk)
        agent.refresh_from_db()
        self.assertTrue(agent.check_token(old))

    def test_duplicate_and_blank_names_are_rejected(self):
        create_agent(actor=self.actor, name="FAKE-VM")
        for name in ("FAKE-VM", " "):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                create_agent(actor=self.actor, name=name)

    def test_direct_writes_and_deletion_are_blocked(self):
        agent, _ = create_agent(actor=self.actor, name="FAKE-VM")
        with self.assertRaises(ValidationError):
            agent.save()
        with self.assertRaises(ValidationError):
            agent.delete()
        with self.assertRaises(ValidationError):
            Agent.objects.filter(pk=agent.pk).update(is_active=True)
        with self.assertRaises(ValidationError):
            Agent.objects.all().delete()

    def test_admin_read_only_and_token_hash_hidden(self):
        agent, raw = create_agent(actor=self.actor, name="FAKE-VM")
        self.client.force_login(self.actor)
        url = reverse("admin:automation_api_agent_change", args=[agent.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, raw)
        self.assertNotContains(response, agent.token_hash)
        self.assertEqual(self.client.post(url, {"name": "OTHER"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:automation_api_agent_add")).status_code, 403)
