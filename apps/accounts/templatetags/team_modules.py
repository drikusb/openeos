"""The "Team modules" card on a team's page: one tile per module, with a live count."""
from datetime import date

from django import template
from django.urls import reverse

from apps.issues.models import Issue
from apps.meetings.models import Meeting
from apps.rocks.models import Rock
from apps.scorecards.models import ScorecardMetric

register = template.Library()


def module_tiles(team):
    """Counts for the team's Rocks, Issues, Scorecard metrics and Meetings."""
    quarter, year = Rock.current_quarter(), Rock.current_year()
    open_rocks = (
        Rock.objects.filter(team=team, quarter=quarter, year=year)
        .exclude(status__in=[Rock.STATUS_COMPLETE, Rock.STATUS_DROPPED])
        .count()
    )
    open_issues = Issue.objects.filter(
        originating_team=team, status__in=[Issue.STATUS_OPEN, Issue.STATUS_IN_IDS]
    ).count()
    active_metrics = ScorecardMetric.objects.filter(
        scorecard__team=team, scorecard__is_active=True, is_active=True
    ).count()
    upcoming_meetings = (
        Meeting.objects.filter(team=team, scheduled_date__gte=date.today())
        .exclude(status=Meeting.STATUS_COMPLETE)
        .count()
    )
    return [
        {'label': 'Rocks', 'icon': 'bi-gem', 'url': reverse('rocks:list'),
         'count': open_rocks, 'caption': f'open in Q{quarter} {year}'},
        {'label': 'Meetings', 'icon': 'bi-calendar3', 'url': reverse('meetings:list'),
         'count': upcoming_meetings, 'caption': 'upcoming'},
        {'label': 'Scorecard', 'icon': 'bi-bar-chart', 'url': reverse('scorecards:list'),
         'count': active_metrics, 'caption': 'active metrics'},
        {'label': 'Issues', 'icon': 'bi-exclamation-triangle', 'url': reverse('issues:list'),
         'count': open_issues, 'caption': 'open'},
    ]


@register.inclusion_tag('accounts/includes/team_modules.html', takes_context=True)
def team_modules(context, team):
    """Render the card. Members get tiles that switch to the team and open the module;
    anyone else (an admin looking at a team they are not on) sees the counts only."""
    request = context['request']
    user = request.user
    is_member = user.is_authenticated and team.members.filter(user=user).exists()
    return {
        'team': team,
        'tiles': module_tiles(team),
        'is_member': is_member,
        'csrf_token': context.get('csrf_token'),
    }
