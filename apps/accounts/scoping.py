"""Helpers that keep every request inside the active organisation and team.

A user may belong to several organisations through Membership. The session
remembers which one is active; every list, form and pk lookup is limited to it.
A request on an organisation's own hostname (see middleware.py) is pinned to
that organisation and ignores the session choice.
"""
from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import Membership, Organization, Team

SESSION_ORG_KEY = 'active_org_id'
SESSION_TEAM_KEY = 'active_team_id'


def get_user_orgs(user):
    if not user.is_authenticated:
        return Organization.objects.none()
    return Organization.objects.filter(memberships__user=user)


def get_active_org(request):
    """Return the host's organisation, else the session-pinned one, else the user's first.

    The result is memoised on the request because the context processor and
    most views each ask for it.
    """
    if not hasattr(request, '_active_org'):
        request._active_org = _resolve_active_org(request)
    return request._active_org


def _resolve_active_org(request):
    host_org = getattr(request, 'host_org', None)
    if host_org is not None:
        user = request.user
        if user.is_superuser or get_user_orgs(user).filter(pk=host_org.pk).exists():
            return host_org
        return None
    orgs = get_user_orgs(request.user)
    stored_id = request.session.get(SESSION_ORG_KEY)
    if stored_id:
        org = orgs.filter(pk=stored_id).first()
        if org:
            return org
    org = orgs.first()
    if org is None:
        return None
    request.session[SESSION_ORG_KEY] = org.pk
    return org


def set_active_org(request, org):
    request.session[SESSION_ORG_KEY] = org.pk
    request.session.pop(SESSION_TEAM_KEY, None)
    request._active_org = org


def get_active_team(request):
    """Return the session-pinned team if valid, else the user's first team in the active org."""
    org = get_active_org(request)
    if org is None:
        return None
    user_teams = request.user.profile.teams.filter(organization=org)
    stored_id = request.session.get(SESSION_TEAM_KEY)
    if stored_id:
        team = user_teams.filter(pk=stored_id).first()
        if team:
            return team
    team = user_teams.first()
    if team is None:
        return None
    request.session[SESSION_TEAM_KEY] = team.pk
    return team


def is_org_admin(user, org):
    if user.is_superuser:
        return True
    if org is None:
        return False
    return Membership.objects.filter(
        user=user, organization=org, role=Membership.ROLE_ADMIN
    ).exists()


def get_org_object_or_404(request, model, org_lookup='team__organization', **kwargs):
    """Like get_object_or_404, but only for records in the active organisation."""
    org = get_active_org(request)
    if org is None:
        raise Http404
    return get_object_or_404(model, **{org_lookup: org}, **kwargs)


class OrgScopedMixin:
    """Limit a single-object generic view to records in the active organisation.

    ``org_lookup`` is the ORM path from the view's model to its Organization.
    """

    org_lookup = 'team__organization'

    def get_queryset(self):
        queryset = super().get_queryset()
        org = get_active_org(self.request)
        if org is None:
            return queryset.none()
        return queryset.filter(**{self.org_lookup: org})


def get_assignable_teams(user, org):
    """Teams ``user`` may file a Rock, To-Do or Issue under within ``org``.

    Members choose from the teams they belong to; organisation admins may
    choose any team in the organisation.
    """
    if user is None or org is None:
        return Team.objects.none()
    teams = Team.objects.filter(organization=org)
    if not is_org_admin(user, org):
        teams = teams.filter(members__user=user)
    return teams.order_by('name')
