"""Write audit events.

Other features call :func:`record` and carry on; a failed audit write is logged
but never raised, so the audit log cannot break the action it describes.
"""
import ipaddress
import logging

from django.db import models

from .models import AuditEvent

logger = logging.getLogger(__name__)

USER_AGENT_MAX_LENGTH = AuditEvent._meta.get_field('user_agent').max_length
ACTOR_LABEL_MAX_LENGTH = AuditEvent._meta.get_field('actor_label').max_length
TARGET_LABEL_MAX_LENGTH = AuditEvent._meta.get_field('target_label').max_length


def record(action, *, request=None, actor=None, organization=None, target=None, details=None):
    """Create and return an :class:`AuditEvent`, or ``None`` if writing it failed.

    ``action`` is a dotted lower-case name such as ``user.login``. When ``request``
    is given, the actor (if authenticated), IP address and user agent are taken
    from it; an explicit ``actor`` always wins. ``target`` may be any model
    instance and is stored as ``app_label.model_name``, its pk and ``str()``.
    """
    try:
        return _record(action, request, actor, organization, target, details)
    except Exception:  # noqa: BLE001 — an audit failure must not break the caller
        logger.exception('Could not record audit event %r', action)
        return None


def _record(action, request, actor, organization, target, details):
    if actor is None and request is not None:
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            actor = user

    fields = {
        'action': action,
        'actor': actor,
        'actor_label': actor.get_username()[:ACTOR_LABEL_MAX_LENGTH] if actor else '',
        'organization': organization,
        'details': details or {},
    }
    if request is not None:
        fields['ip_address'] = client_ip(request)
        fields['user_agent'] = request.META.get('HTTP_USER_AGENT', '')[:USER_AGENT_MAX_LENGTH]
    if isinstance(target, models.Model):
        meta = target._meta
        fields['target_type'] = f'{meta.app_label}.{meta.model_name}'
        fields['target_id'] = str(target.pk)
        fields['target_label'] = str(target)[:TARGET_LABEL_MAX_LENGTH]
    return AuditEvent.objects.create(**fields)


def client_ip(request):
    """Return the client's IP address, honouring the first X-Forwarded-For value."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    raw = forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR', '')
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None
