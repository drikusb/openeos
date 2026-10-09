from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accountability.models import AccountabilityNode, AccountabilityRole
from apps.accounts.models import Membership, Organization, Team
from apps.accounts.scoping import SESSION_TEAM_KEY
from apps.issues.models import Issue
from apps.meetings.models import Meeting
from apps.rocks.models import Rock, RockDependency, RockMilestone
from apps.scorecards.models import Scorecard, ScorecardEntry, ScorecardMetric
from apps.todos.models import ToDo
from apps.vto.models import VTO, VTOCoreValue


def build_org(label):
    """Create an organisation with one admin user and one record of every kind."""
    org = Organization.objects.create(name=f'{label} Org')
    team = Team.objects.create(organization=org, name=f'{label} Team')
    user = User.objects.create_user(username=f'{label.lower()}admin', password='pw')
    Membership.objects.create(user=user, organization=org, role=Membership.ROLE_ADMIN)
    user.profile.teams.add(team)

    rock = Rock.objects.create(
        title=f'{label} Rock', owner=user, team=team,
        quarter=1, year=2026, due_date=date(2026, 3, 31),
    )
    other_rock = Rock.objects.create(
        title=f'{label} Rock 2', owner=user, team=team,
        quarter=1, year=2026, due_date=date(2026, 3, 31),
    )
    dependency = RockDependency.objects.create(rock=rock, depends_on_rock=other_rock)
    milestone = RockMilestone.objects.create(rock=rock, title=f'{label} Milestone')
    issue = Issue.objects.create(
        title=f'{label} Issue', originating_team=team, created_by=user,
    )
    todo = ToDo.objects.create(title=f'{label} To-Do', owner=user, team=team)
    scorecard = Scorecard.objects.create(name=f'{label} Scorecard', team=team)
    metric = ScorecardMetric.objects.create(
        scorecard=scorecard, name=f'{label} Metric', owner=user, goal_value=10,
    )
    entry = ScorecardEntry.objects.create(
        metric=metric, period_start=date(2026, 1, 5), value=5, entered_by=user,
    )
    core_value = VTOCoreValue.objects.create(vto=VTO.for_org(org), name=f'{label} Value')
    meeting = Meeting.objects.create(team=team, scheduled_date=date(2026, 1, 5), created_by=user)
    node = AccountabilityNode.objects.create(organization=org, name=f'{label} Seat')
    role = AccountabilityRole.objects.create(node=node, description=f'{label} duty')

    return {
        'org': org, 'team': team, 'user': user, 'rock': rock, 'dependency': dependency,
        'milestone': milestone, 'issue': issue, 'todo': todo, 'scorecard': scorecard,
        'metric': metric, 'entry': entry, 'core_value': core_value, 'meeting': meeting,
        'node': node, 'role': role,
    }


def pk_urls(f):
    """Every URL that reaches a record by primary key, with the POST data it expects."""
    gets = [
        f'/rocks/{f["rock"].pk}/',
        f'/rocks/{f["rock"].pk}/edit/',
        f'/rocks/{f["rock"].pk}/delete/',
        f'/rocks/milestones/{f["milestone"].pk}/edit/',
        f'/issues/{f["issue"].pk}/',
        f'/issues/{f["issue"].pk}/edit/',
        f'/issues/{f["issue"].pk}/delete/',
        f'/todos/{f["todo"].pk}/edit/',
        f'/todos/{f["todo"].pk}/delete/',
        f'/scorecards/{f["scorecard"].pk}/',
        f'/scorecards/{f["scorecard"].pk}/edit/',
        f'/scorecards/{f["scorecard"].pk}/delete/',
        f'/scorecards/{f["scorecard"].pk}/enter/',
        f'/scorecards/{f["scorecard"].pk}/metrics/add/',
        f'/scorecards/metric/{f["metric"].pk}/edit/',
        f'/vto/core-values/{f["core_value"].pk}/edit/',
        f'/vto/core-values/{f["core_value"].pk}/delete/',
        f'/teams/{f["team"].pk}/',
        f'/teams/{f["team"].pk}/edit/',
        f'/meetings/{f["meeting"].pk}/',
        f'/meetings/{f["meeting"].pk}/print/',
        f'/accountability/nodes/{f["node"].pk}/edit/',
        f'/accountability/nodes/{f["node"].pk}/delete/',
        f'/accountability/nodes/{f["node"].pk}/roles/add/',
        f'/accountability/roles/{f["role"].pk}/edit/',
        f'/accountability/roles/{f["role"].pk}/delete/',
    ]
    posts = [
        (f'/rocks/{f["rock"].pk}/status/', {'status': Rock.STATUS_ON_TRACK}),
        (f'/rocks/{f["rock"].pk}/checkins/add/', {'confidence': Rock.STATUS_ON_TRACK}),
        (f'/rocks/{f["rock"].pk}/dependency/add/', {}),
        (f'/rocks/{f["rock"].pk}/milestones/add/', {'title': 'x'}),
        (f'/rocks/{f["rock"].pk}/issues/link/', {'issue_id': f['issue'].pk}),
        (f'/rocks/{f["rock"].pk}/issues/unlink/', {'issue_id': f['issue'].pk}),
        (f'/rocks/dependency/{f["dependency"].pk}/remove/', {}),
        (f'/rocks/milestones/{f["milestone"].pk}/toggle/', {}),
        (f'/rocks/milestones/{f["milestone"].pk}/edit/', {'title': 'x'}),
        (f'/rocks/milestones/{f["milestone"].pk}/delete/', {}),
        (f'/issues/{f["issue"].pk}/status/', {'status': Issue.STATUS_IN_IDS}),
        (f'/issues/{f["issue"].pk}/delegate/', {}),
        (f'/issues/{f["issue"].pk}/comment/', {'notes': 'x'}),
        (f'/todos/{f["todo"].pk}/complete/', {}),
        (f'/todos/{f["todo"].pk}/escalate/', {}),
        (f'/scorecards/{f["scorecard"].pk}/enter/', {}),
        (f'/scorecards/metric/{f["metric"].pk}/delete/', {}),
        (f'/scorecards/entry/{f["entry"].pk}/escalate/', {}),
        (f'/teams/{f["team"].pk}/members/', {'users': [f['user'].pk]}),
        (f'/teams/{f["team"].pk}/switch/', {}),
        (f'/meetings/{f["meeting"].pk}/start/', {}),
        (f'/accountability/nodes/{f["node"].pk}/move/', {'direction': 'up'}),
    ]
    return gets, posts


class OrganisationIsolationTest(TestCase):
    """A user in one organisation cannot reach another organisation's records by pk."""

    def setUp(self):
        self.mine = build_org('Mine')
        self.theirs = build_org('Theirs')
        self.client.force_login(self.mine['user'])

    def test_other_org_records_are_not_found(self):
        gets, posts = pk_urls(self.theirs)
        for url in gets:
            with self.subTest(method='GET', url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        for url, data in posts:
            with self.subTest(method='POST', url=url):
                self.assertEqual(self.client.post(url, data).status_code, 404)

    def test_own_org_records_are_reachable(self):
        gets, posts = pk_urls(self.mine)
        for url in gets:
            with self.subTest(method='GET', url=url):
                self.assertIn(self.client.get(url).status_code, (200, 302))
        for url, data in posts:
            with self.subTest(method='POST', url=url):
                self.assertIn(self.client.post(url, data).status_code, (200, 302))

    def test_cannot_link_another_orgs_issue_to_own_rock(self):
        url = f'/rocks/{self.mine["rock"].pk}/issues/link/'
        resp = self.client.post(url, {'issue_id': self.theirs['issue'].pk})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(self.mine['rock'].linked_issues.exists())

    def test_cannot_edit_another_orgs_team_members(self):
        url = f'/teams/{self.theirs["team"].pk}/members/'
        resp = self.client.post(url, {'users': [self.mine['user'].pk]})
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn(self.theirs['team'], self.mine['user'].profile.teams.all())

    def test_user_without_org_is_not_found(self):
        orphan = User.objects.create_user(username='orphan', password='pw')
        self.client.force_login(orphan)
        self.assertEqual(self.client.get(f'/rocks/{self.mine["rock"].pk}/').status_code, 404)


class TeamSwitchRedirectTest(TestCase):
    def setUp(self):
        self.mine = build_org('Mine')
        self.client.force_login(self.mine['user'])

    def test_redirects_to_next_on_same_host(self):
        url = f'/teams/{self.mine["team"].pk}/switch/'
        resp = self.client.post(url, {'next': '/rocks/'})
        self.assertRedirects(resp, '/rocks/', fetch_redirect_response=False)
        self.assertEqual(self.client.session[SESSION_TEAM_KEY], self.mine['team'].pk)

    def test_ignores_next_on_another_host(self):
        url = f'/teams/{self.mine["team"].pk}/switch/'
        resp = self.client.post(url, {'next': 'https://evil.example/phish'})
        self.assertRedirects(resp, '/', fetch_redirect_response=False)
