from datetime import date

from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Membership, Organization, Team
from apps.rocks.models import Rock


class RockCsvExportTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Export Org')
        self.team = Team.objects.create(organization=self.org, name='Export Team')
        self.other_team = Team.objects.create(organization=self.org, name='Other Team')

        self.owner = User.objects.create_user(
            username='exportowner', first_name='Export', last_name='Owner',
            email='owner@example.com', password='pw',
        )
        Membership.objects.create(user=self.owner, organization=self.org)
        self.owner.profile.teams.add(self.team)

        self.rock = Rock.objects.create(
            title='Ship the export feature', owner=self.owner, team=self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31),
            status=Rock.STATUS_ON_TRACK,
        )
        # Belongs to a different team in the same org — must not appear.
        self.other_team_rock = Rock.objects.create(
            title='Other team rock', owner=self.owner, team=self.other_team,
            quarter=1, year=2026, due_date=date(2026, 3, 31),
        )
        # Same team, different quarter — must not appear when Q1 2026 is requested.
        self.other_quarter_rock = Rock.objects.create(
            title='Next quarter rock', owner=self.owner, team=self.team,
            quarter=2, year=2026, due_date=date(2026, 6, 30),
        )

    def test_export_returns_csv_content_type(self):
        self.client.force_login(self.owner)
        resp = self.client.get('/rocks/export/', {'quarter': 1, 'year': 2026})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp['Content-Type'].startswith('text/csv'))

    def test_export_includes_rock_from_active_team_and_quarter(self):
        self.client.force_login(self.owner)
        resp = self.client.get('/rocks/export/', {'quarter': 1, 'year': 2026})
        body = resp.content.decode()
        self.assertIn('Ship the export feature', body)
        self.assertIn('Export Owner', body)
        self.assertIn('On Track', body)

    def test_export_excludes_rock_from_other_team(self):
        self.client.force_login(self.owner)
        resp = self.client.get('/rocks/export/', {'quarter': 1, 'year': 2026})
        body = resp.content.decode()
        self.assertNotIn('Other team rock', body)

    def test_export_excludes_rock_from_other_quarter(self):
        self.client.force_login(self.owner)
        resp = self.client.get('/rocks/export/', {'quarter': 1, 'year': 2026})
        body = resp.content.decode()
        self.assertNotIn('Next quarter rock', body)

    def test_logged_out_access_redirects_to_login(self):
        resp = self.client.get('/rocks/export/', {'quarter': 1, 'year': 2026})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith('/accounts/login/'))
        self.assertIn('next=', resp.url)
