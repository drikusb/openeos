import csv
import io

from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Membership, Organization, Team
from apps.issues.models import Issue


class IssueCsvExportViewTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Export Org')
        self.team = Team.objects.create(organization=self.org, name='Export Team')
        self.other_team = Team.objects.create(organization=self.org, name='Other Team')

        self.user = User.objects.create_user(username='exporter', password='pw')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Membership.ROLE_ADMIN,
        )
        self.user.profile.teams.add(self.team)

        self.open_issue = Issue.objects.create(
            title='Open Issue', originating_team=self.team, status=Issue.STATUS_OPEN,
            created_by=self.user,
        )
        self.delegated_issue = Issue.objects.create(
            title='Delegated Issue', originating_team=self.team, status=Issue.STATUS_IN_IDS,
            delegated_to_team=self.other_team, created_by=self.user,
        )
        self.dropped_issue = Issue.objects.create(
            title='Dropped Issue', originating_team=self.team, status=Issue.STATUS_DROPPED,
            created_by=self.user,
        )
        self.resolved_issue = Issue.objects.create(
            title='Resolved Issue', originating_team=self.team, status=Issue.STATUS_RESOLVED,
            created_by=self.user,
        )
        self.other_team_issue = Issue.objects.create(
            title='Other Team Issue', originating_team=self.other_team, status=Issue.STATUS_OPEN,
            created_by=self.user,
        )

    def _rows(self, response):
        content = response.content.decode('utf-8')
        return list(csv.reader(io.StringIO(content)))

    def test_export_returns_csv_content_type(self):
        self.client.force_login(self.user)
        resp = self.client.get('/issues/export/')
        self.assertTrue(resp['Content-Type'].startswith('text/csv'))

    def test_open_issue_included_with_status_and_delegation(self):
        self.client.force_login(self.user)
        resp = self.client.get('/issues/export/')
        rows = self._rows(resp)
        titles = [row[0] for row in rows]
        self.assertIn('Open Issue', titles)
        self.assertIn('Delegated Issue', titles)

        delegated_row = next(row for row in rows if row[0] == 'Delegated Issue')
        # Title, Type, Status, Originating Team, Delegated To, Created By, Created At
        self.assertEqual(delegated_row[2], 'In IDS')
        self.assertEqual(delegated_row[4], 'Other Team')

    def test_dropped_issue_excluded_by_default(self):
        self.client.force_login(self.user)
        resp = self.client.get('/issues/export/')
        titles = [row[0] for row in self._rows(resp)]
        self.assertNotIn('Dropped Issue', titles)
        self.assertNotIn('Resolved Issue', titles)

    def test_dropped_issue_included_with_status_all(self):
        self.client.force_login(self.user)
        resp = self.client.get('/issues/export/', {'status': 'all'})
        titles = [row[0] for row in self._rows(resp)]
        self.assertIn('Dropped Issue', titles)
        self.assertIn('Resolved Issue', titles)

    def test_dropped_issue_included_with_explicit_status_filter(self):
        self.client.force_login(self.user)
        resp = self.client.get('/issues/export/', {'status': 'dropped'})
        titles = [row[0] for row in self._rows(resp)]
        self.assertIn('Dropped Issue', titles)
        self.assertNotIn('Open Issue', titles)

    def test_other_team_issue_not_included(self):
        self.client.force_login(self.user)
        resp = self.client.get('/issues/export/', {'status': 'all'})
        titles = [row[0] for row in self._rows(resp)]
        self.assertNotIn('Other Team Issue', titles)

    def test_logged_out_redirects_to_login(self):
        resp = self.client.get('/issues/export/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.url)
