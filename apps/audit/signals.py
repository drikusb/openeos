"""Record authentication events. Connected from :class:`apps.audit.apps.AuditConfig`."""
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from apps.accounts.scoping import SESSION_ORG_KEY, get_user_orgs

from .services import record


def organization_for(user, request=None):
    """The organisation a sign-in event belongs to, or None when that is ambiguous.

    A user in exactly one organisation is attributed to it. A user in several is
    attributed to the one active in their session, if any; otherwise the event is
    left unattributed and appears only in the Django admin.
    """
    if user is None or not user.is_authenticated:
        return None
    orgs = list(get_user_orgs(user)[:2])
    if len(orgs) == 1:
        return orgs[0]
    if len(orgs) > 1 and request is not None and hasattr(request, 'session'):
        stored_id = request.session.get(SESSION_ORG_KEY)
        if stored_id:
            return get_user_orgs(user).filter(pk=stored_id).first()
    return None


@receiver(user_logged_in, dispatch_uid='audit.user_logged_in')
def on_user_logged_in(sender, request, user, **kwargs):
    record(
        'user.login', request=request, actor=user,
        organization=organization_for(user, request),
    )


@receiver(user_logged_out, dispatch_uid='audit.user_logged_out')
def on_user_logged_out(sender, request, user, **kwargs):
    if user is None or not user.is_authenticated:
        return
    record(
        'user.logout', request=request, actor=user,
        organization=organization_for(user, request),
    )


@receiver(user_login_failed, dispatch_uid='audit.user_login_failed')
def on_user_login_failed(sender, credentials, request=None, **kwargs):
    # A failed attempt against a real account is shown to that account's
    # organisation; the actor stays empty because nobody proved who they were.
    username = credentials.get('username')
    user = get_user_model()._default_manager.filter(username=username).first() if username else None
    record(
        'user.login_failed', request=request,
        organization=organization_for(user, request),
        details={'username': username},
    )
