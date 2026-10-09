from datetime import date

from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Membership, Organization, Team
from apps.rocks.models import Rock


class VTOCompanyRocksTest(TestCase):
    """Only company-wide Rocks should appear on the VTO (#3, #4)."""

    def setUp(self):
        self.org = Organization.objects.create(name='VTO Rocks Org')
        self.other_org = Organization.objects.create(name='Other Org')

        self.team_a = Team.objects.create(organization=self.org, name='Team A')
        self.team_b = Team.objects.create(organization=self.org, name='Team B')
        self.other_team = Team.objects.create(organization=self.other_org, name='Other Team')

        self.user = User.objects.create_user(username='vtouser', password='pw')
        Membership.objects.create(user=self.user, organization=self.org)
        self.user.profile.teams.add(self.team_a)

        q, y = Rock.current_quarter(), Rock.current_year()
        due = Rock.quarter_end_date(q, y)

        self.company_rock_a = Rock.objects.create(
            title='Company Rock A', owner=self.user, team=self.team_a,
            quarter=q, year=y, due_date=due, is_company_rock=True,
        )
        self.company_rock_b = Rock.objects.create(
            title='Company Rock B', owner=self.user, team=self.team_b,
            quarter=q, year=y, due_date=due, is_company_rock=True,
        )
        self.team_rock = Rock.objects.create(
            title='Team-only Rock', owner=self.user, team=self.team_a,
            quarter=q, year=y, due_date=due, is_company_rock=False,
        )
        self.other_org_company_rock = Rock.objects.create(
            title='Other Org Company Rock', owner=self.user, team=self.other_team,
            quarter=q, year=y, due_date=due, is_company_rock=True,
        )

    def test_vto_detail_lists_only_company_rocks_for_the_active_org(self):
        self.client.force_login(self.user)
        resp = self.client.get('/vto/')
        rocks = list(resp.context['rocks'])
        self.assertIn(self.company_rock_a, rocks)
        self.assertIn(self.company_rock_b, rocks)
        self.assertNotIn(self.team_rock, rocks)
        self.assertNotIn(self.other_org_company_rock, rocks)

    def test_vto_print_lists_only_company_rocks_for_the_active_org(self):
        self.client.force_login(self.user)
        resp = self.client.get('/vto/print/')
        rocks = list(resp.context['rocks'])
        self.assertIn(self.company_rock_a, rocks)
        self.assertIn(self.company_rock_b, rocks)
        self.assertNotIn(self.team_rock, rocks)
        self.assertNotIn(self.other_org_company_rock, rocks)

    def test_empty_state_mentions_company_wide(self):
        self.team_rock.delete()
        self.company_rock_a.delete()
        self.company_rock_b.delete()
        self.client.force_login(self.user)
        resp = self.client.get('/vto/')
        self.assertContains(resp, 'No company-wide Rocks')
