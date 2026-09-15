"""Local agent credential lifecycle only; no API or worker integration."""

import hashlib
import secrets

from django.db import transaction
from django.utils import timezone

from audit.models import AuditEvent
from workorders.services import require_permission
from .models import Agent


def _new_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(64)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


@transaction.atomic
def create_agent(*, actor, name: str) -> tuple[Agent, str]:
    """Return the raw token once to the caller; never persist or log it."""
    require_permission(actor, "automation_api.add_agent")
    raw, digest = _new_token()
    agent = Agent(name=name.strip(), token_hash=digest)
    agent.save(_service_write=True, force_insert=True)
    AuditEvent.objects.create(agent=agent, actor=actor, kind=AuditEvent.Kind.AGENT_CREATED)
    return agent, raw


@transaction.atomic
def rotate_agent_token(*, actor, agent_id) -> tuple[Agent, str]:
    require_permission(actor, "automation_api.change_agent")
    agent = Agent.objects.select_for_update().get(pk=agent_id)
    raw, digest = _new_token()
    agent.token_hash = digest
    agent.token_rotated_at = timezone.now()
    agent.save(_service_write=True)
    AuditEvent.objects.create(agent=agent, actor=actor, kind=AuditEvent.Kind.AGENT_TOKEN_ROTATED)
    return agent, raw


@transaction.atomic
def disable_agent(*, actor, agent_id) -> Agent:
    require_permission(actor, "automation_api.change_agent")
    agent = Agent.objects.select_for_update().get(pk=agent_id)
    agent.is_active = False
    agent.save(_service_write=True)
    AuditEvent.objects.create(agent=agent, actor=actor, kind=AuditEvent.Kind.AGENT_DISABLED)
    return agent
