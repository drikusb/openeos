"""Helpers that keep every request inside the active organisation and team.

A user may belong to several organisations through Membership. The session
remembers which one is active; every list, form and pk lookup is limited to it.
"""
from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import Membership, Organization

SESSION_ORG_KEY = 'active_org_id'
SESSION_TEAM_KEY = 'active_team_id'


def get_user_orgs(user):
    if not user.is_authenticated:
        return Organization.objects.none()
    return Organization.objects.filter(memberships__user=user)


def get_active_org(request):
    """Return the session-pinned organisation if valid, else the user's first one."""
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
