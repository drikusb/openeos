from .scoping import get_active_org, get_active_team, get_user_orgs


def active_context(request):
    """Inject the active organisation and team, and the switcher choices, into templates."""
    if not request.user.is_authenticated:
        return {}
    org = get_active_org(request)
    team = get_active_team(request)
    user_teams = []
    if org is not None:
        user_teams = list(request.user.profile.teams.filter(organization=org).order_by('name'))
    return {
        'active_org': org,
        'user_orgs': list(get_user_orgs(request.user).order_by('name')),
        'active_team': team,
        'user_teams': user_teams,
    }
