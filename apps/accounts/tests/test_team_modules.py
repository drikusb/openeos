from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Membership, Organization, Team, UserProfile
from apps.issues.models import Issue
from apps.meetings.models import Meeting
from apps.rocks.models import Rock
from apps.scorecards.models import Scorecard, ScorecardMetric


class TeamModulesCardTest(TestCase):
    """The team page's module tiles show live counts and open the module for members."""

    def setUp(self):
        self.org = Organization.objects.create(name='Harbour')
        self.team = Team.objects.create(organization=self.org, name='Leadership')
        self.other_team = Team.objects.create(organization=self.org, name='Operations')
        self.member = User.objects.create_user(username='member', password='pw')
        self.admin = User.objects.create_user(username='admin', password='pw')
        for user, role in ((self.member, Membership.ROLE_MEMBER), (self.admin, Membership.ROLE_ADMIN)):
            Membership.objects.create(user=user, organization=self.org, role=role)
            UserProfile.objects.get_or_create(user=user)
        self.member.profile.teams.add(self.team)
        self.admin.profile.teams.add(self.other_team)

        quarter, year = Rock.current_quarter(), Rock.current_year()
        other_quarter = 1 if quarter != 1 else 2
        common = {'owner': self.member, 'created_by': self.member, 'due_date': date.today()}
        Rock.objects.create(title='Open now', team=self.team, quarter=quarter, year=year, **common)
        Rock.objects.create(
            title='Done', team=self.team, quarter=quarter, year=year,
            status=Rock.STATUS_COMPLETE, **common,
        )
        Rock.objects.create(
            title='Another quarter', team=self.team, quarter=other_quarter, year=year, **common
        )
        Rock.objects.create(
            title='Other team', team=self.other_team, quarter=quarter, year=year, **common
        )
        Issue.objects.create(title='Open issue', originating_team=self.team, created_by=self.member)
        Issue.objects.create(
            title='In IDS', originating_team=self.team, created_by=self.member,
            status=Issue.STATUS_IN_IDS,
        )
        Issue.objects.create(
            title='Resolved', originating_team=self.team, created_by=self.member,
            status=Issue.STATUS_RESOLVED,
        )
        scorecard = Scorecard.objects.create(name='Leadership Scorecard', team=self.team)
        ScorecardMetric.objects.create(scorecard=scorecard, name='Active', owner=self.member, goal_value=1)
        ScorecardMetric.objects.create(
            scorecard=scorecard, name='Retired', owner=self.member, goal_value=1, is_active=False
        )
        Meeting.objects.create(
            team=self.team, scheduled_date=date.today() + timedelta(days=3), created_by=self.member
        )
        Meeting.objects.create(
            team=self.team, scheduled_date=date.today() - timedelta(days=7),
            status=Meeting.STATUS_COMPLETE, created_by=self.member,
        )
        self.url = reverse('accounts:team_detail', args=[self.team.pk])

    def test_phase_placeholders_are_gone(self):
        self.client.force_login(self.member)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Phase')

    def test_counts_are_the_teams_own(self):
        self.client.force_login(self.member)
        resp = self.client.get(self.url)
        tiles = {t['label']: t['count'] for t in resp.context['tiles']}
        self.assertEqual(tiles, {'Rocks': 1, 'Meetings': 1, 'Scorecard': 1, 'Issues': 2})
        self.assertContains(resp, 'open in Q')

    def test_member_gets_tiles_that_switch_to_the_team_and_open_the_module(self):
        self.client.force_login(self.member)
        resp = self.client.get(self.url)
        switch = reverse('accounts:team_switch', args=[self.team.pk])
        self.assertContains(resp, 'team-module-tile', count=4)
        self.assertContains(resp, f'action="{switch}"')
        self.assertContains(resp, f'value="{reverse("rocks:list")}"')
        # Following a tile pins the team in the session and lands on the module.
        resp = self.client.post(switch, {'next': reverse('rocks:list')})
        self.assertRedirects(resp, reverse('rocks:list'), fetch_redirect_response=False)
        self.assertEqual(self.client.session['active_team_id'], self.team.pk)

    def test_non_member_sees_counts_but_no_tiles_to_open(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'team-module-tile')
        self.assertContains(resp, 'Join this team to open its modules')
        tiles = {t['label']: t['count'] for t in resp.context['tiles']}
        self.assertEqual(tiles['Rocks'], 1)
