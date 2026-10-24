"""The Rocks list can show every team the user may see, not only the navbar's active team."""
from datetime import date

from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Membership, Organization, Team
from apps.rocks.models import Rock
from apps.rocks.views import SCOPE_SESSION_KEY

LIST_URL = '/rocks/'
EXPORT_URL = '/rocks/export/'
Q1 = {'quarter': 1, 'year': 2026}


class AllTeamsScopeTestBase(TestCase):
    """One organisation, three teams.

    ``member`` is on Alpha and Beta; ``admin`` is an organisation admin on Alpha
    only; ``loner`` is a member of the organisation but on no team. Alpha is
    everyone's active team because it sorts first by name.
    """

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Scope Org')
        cls.alpha = Team.objects.create(organization=cls.org, name='Alpha')
        cls.beta = Team.objects.create(organization=cls.org, name='Beta')
        cls.gamma = Team.objects.create(organization=cls.org, name='Gamma')

        cls.member = User.objects.create_user(
            username='scopemember', first_name='Alice', last_name='Member', password='pw'
        )
        Membership.objects.create(user=cls.member, organization=cls.org)
        cls.member.profile.teams.add(cls.alpha, cls.beta)

        cls.admin = User.objects.create_user(
            username='scopeadmin', first_name='Zoe', last_name='Admin', password='pw'
        )
        Membership.objects.create(
            user=cls.admin, organization=cls.org, role=Membership.ROLE_ADMIN
        )
        cls.admin.profile.teams.add(cls.alpha)

        cls.loner = User.objects.create_user(username='scopeloner', password='pw')
        Membership.objects.create(user=cls.loner, organization=cls.org)

        due = date(2026, 3, 31)
        cls.alpha_one = Rock.objects.create(
            title='Alpha rock one', owner=cls.member, team=cls.alpha,
            quarter=1, year=2026, due_date=due, status=Rock.STATUS_ON_TRACK,
        )
        cls.alpha_two = Rock.objects.create(
            title='Alpha rock two', owner=cls.admin, team=cls.alpha,
            quarter=1, year=2026, due_date=due, status=Rock.STATUS_COMPLETE,
        )
        cls.beta_rock = Rock.objects.create(
            title='Beta rock', owner=cls.member, team=cls.beta,
            quarter=1, year=2026, due_date=due, status=Rock.STATUS_OFF_TRACK,
        )
        cls.gamma_rock = Rock.objects.create(
            title='Gamma rock', owner=cls.admin, team=cls.gamma,
            quarter=1, year=2026, due_date=due, status=Rock.STATUS_ON_TRACK,
        )
        # Only Beta has a Rock in Q2, so it is invisible in the default scope.
        cls.beta_next = Rock.objects.create(
            title='Beta next quarter', owner=cls.member, team=cls.beta,
            quarter=2, year=2026, due_date=date(2026, 6, 30),
        )

    @staticmethod
    def team_names(resp):
        return [team.name for team, _ in resp.context['teams_rocks']]

    @staticmethod
    def rock_titles(resp):
        return [rock.title for rock in resp.context['rocks']]


class DefaultScopeTest(AllTeamsScopeTestBase):
    def test_default_shows_only_the_active_team(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, Q1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['scope'], 'team')
        self.assertEqual(self.team_names(resp), ['Alpha'])
        self.assertEqual(self.rock_titles(resp), ['Alpha rock one', 'Alpha rock two'])
        self.assertNotContains(resp, 'Beta rock')
        self.assertNotContains(resp, 'Gamma rock')

    def test_unknown_scope_value_is_ignored(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {**Q1, 'scope': 'bogus'})
        self.assertEqual(resp.context['scope'], 'team')
        self.assertNotIn(SCOPE_SESSION_KEY, self.client.session)

    def test_toggle_is_offered_to_a_user_on_several_teams(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, Q1)
        self.assertContains(resp, 'This team')
        self.assertContains(resp, 'All teams')
        self.assertContains(resp, 'scope=all')


class AllScopeTest(AllTeamsScopeTestBase):
    def test_all_scope_groups_the_users_teams_and_skips_others(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {**Q1, 'scope': 'all'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['scope'], 'all')
        self.assertEqual(self.team_names(resp), ['Alpha', 'Beta'])
        self.assertEqual(
            self.rock_titles(resp), ['Alpha rock one', 'Alpha rock two', 'Beta rock']
        )
        self.assertContains(resp, '<h5 class="mb-0 me-2">Alpha</h5>', html=False)
        self.assertContains(resp, '<h5 class="mb-0 me-2">Beta</h5>', html=False)
        self.assertNotContains(resp, 'Gamma rock')
        self.assertEqual(
            [t.name for t in resp.context['scoped_teams']], ['Alpha', 'Beta']
        )

    def test_org_admin_sees_every_team_in_the_organisation(self):
        self.client.force_login(self.admin)
        resp = self.client.get(LIST_URL, {**Q1, 'scope': 'all'})
        self.assertEqual(self.team_names(resp), ['Alpha', 'Beta', 'Gamma'])
        self.assertContains(resp, 'Gamma rock')

    def test_scope_persists_across_a_quarter_change(self):
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {**Q1, 'scope': 'all'})
        self.assertEqual(self.client.session[SCOPE_SESSION_KEY], 'all')
        resp = self.client.get(LIST_URL, {'quarter': 2, 'year': 2026})
        self.assertEqual(resp.context['scope'], 'all')
        self.assertEqual(self.team_names(resp), ['Beta'])
        self.assertContains(resp, 'Beta next quarter')

    def test_scope_team_returns_to_the_active_team(self):
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {**Q1, 'scope': 'all'})
        resp = self.client.get(LIST_URL, {**Q1, 'scope': 'team'})
        self.assertEqual(resp.context['scope'], 'team')
        self.assertEqual(self.client.session[SCOPE_SESSION_KEY], 'team')
        self.assertEqual(self.team_names(resp), ['Alpha'])
        resp = self.client.get(LIST_URL, Q1)
        self.assertEqual(self.team_names(resp), ['Alpha'])

    def test_status_filter_applies_across_teams(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {**Q1, 'scope': 'all', 'status': 'off_track'})
        self.assertEqual(self.rock_titles(resp), ['Beta rock'])
        self.assertEqual(self.team_names(resp), ['Beta'])
        resp = self.client.get(LIST_URL, {**Q1, 'scope': 'all', 'status': 'on_track'})
        self.assertEqual(self.rock_titles(resp), ['Alpha rock one'])

    def test_my_rocks_spans_teams(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {**Q1, 'scope': 'all'})
        self.assertEqual(
            [r.title for r in resp.context['my_rocks']], ['Alpha rock one', 'Beta rock']
        )

    def test_empty_state_names_all_teams(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'quarter': 3, 'year': 2026, 'scope': 'all'})
        self.assertEqual(resp.context['teams_rocks'], [])
        self.assertContains(resp, 'No Rocks for Q3 2026 on any of your teams.')

    def test_user_with_no_teams_gets_an_empty_list(self):
        self.client.force_login(self.loner)
        resp = self.client.get(LIST_URL, Q1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['teams_rocks'], [])
        resp = self.client.get(LIST_URL, {**Q1, 'scope': 'all'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['teams_rocks'], [])
        self.assertEqual(resp.context['scoped_teams'], [])
        self.assertNotContains(resp, 'All teams')


class ScopeHintTest(AllTeamsScopeTestBase):
    def test_team_scope_hints_at_rocks_on_other_teams(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, Q1)
        self.assertContains(resp, 'Showing Alpha')
        self.assertContains(resp, '1 more on other teams')
        self.assertEqual(resp.context['other_rocks_total'], 1)
        self.assertEqual(
            [(t.name, n) for t, n in resp.context['other_team_counts']], [('Beta', 1)]
        )
        # Autoescaping renders the href's ampersands as entities.
        self.assertContains(resp, 'quarter=1&amp;year=2026&amp;scope=all')
        self.assertContains(resp, 'title="Beta: 1"')

    def test_hint_counts_only_teams_the_user_may_see(self):
        """Gamma's Rock counts for the admin but not for the member."""
        self.client.force_login(self.admin)
        resp = self.client.get(LIST_URL, Q1)
        self.assertContains(resp, '2 more on other teams')
        self.assertEqual(
            [(t.name, n) for t, n in resp.context['other_team_counts']],
            [('Beta', 1), ('Gamma', 1)],
        )

    def test_hint_honours_the_status_filter(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {**Q1, 'status': 'on_track'})
        self.assertNotContains(resp, 'more on other teams')
        resp = self.client.get(LIST_URL, {**Q1, 'status': 'off_track'})
        self.assertContains(resp, '1 more on other teams')
        self.assertContains(resp, 'status=off_track&amp;scope=all')

    def test_hint_is_absent_when_other_teams_have_nothing(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'quarter': 3, 'year': 2026})
        self.assertEqual(resp.context['other_rocks_total'], 0)
        self.assertNotContains(resp, 'more on other teams')
        self.assertNotContains(resp, 'Showing Alpha')

    def test_all_scope_hint_links_back_to_the_team(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {**Q1, 'scope': 'all'})
        self.assertContains(resp, 'Showing all your teams (2)')
        self.assertContains(resp, 'Back to Alpha')
        self.assertContains(resp, 'quarter=1&amp;year=2026&amp;scope=team')
        self.assertNotContains(resp, 'more on other teams')


class AllTeamsCsvExportTest(AllTeamsScopeTestBase):
    def test_export_has_a_team_column(self):
        self.client.force_login(self.member)
        resp = self.client.get(EXPORT_URL, Q1)
        header = resp.content.decode().splitlines()[0]
        self.assertEqual(header, 'Title,Team,Owner,Status,Quarter,Year,Due Date')

    def test_default_export_covers_only_the_active_team(self):
        self.client.force_login(self.member)
        body = self.client.get(EXPORT_URL, Q1).content.decode()
        self.assertIn('Alpha rock one,Alpha,', body)
        self.assertNotIn('Beta rock', body)

    def test_export_in_all_scope_covers_every_visible_team(self):
        self.client.force_login(self.member)
        body = self.client.get(EXPORT_URL, {**Q1, 'scope': 'all'}).content.decode()
        self.assertIn('Alpha rock one,Alpha,Alice Member,On Track,1,2026,2026-03-31', body)
        self.assertIn('Beta rock,Beta,Alice Member,Off Track,1,2026,2026-03-31', body)
        self.assertNotIn('Gamma rock', body)
        self.assertNotIn('Beta next quarter', body)

    def test_export_follows_the_scope_kept_in_the_session(self):
        """The Export CSV link carries no scope; it exports what the list shows."""
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {**Q1, 'scope': 'all'})
        body = self.client.get(EXPORT_URL, Q1).content.decode()
        self.assertIn('Beta rock', body)
