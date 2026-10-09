from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import Membership, Organization, Team
from apps.scorecards.models import Scorecard, ScorecardEntry, ScorecardMetric
from apps.scorecards.views import _build_periods


def build_scorecard(label):
    """Create an organisation with a team, user, scorecard and one metric."""
    org = Organization.objects.create(name=f'{label} Org')
    team = Team.objects.create(organization=org, name=f'{label} Team')
    user = User.objects.create_user(
        username=f'{label.lower()}user', email=f'{label.lower()}@example.com', password='pw'
    )
    Membership.objects.create(user=user, organization=org, role=Membership.ROLE_ADMIN)
    user.profile.teams.add(team)

    scorecard = Scorecard.objects.create(name=f'{label} Scorecard', team=team)
    metric = ScorecardMetric.objects.create(
        scorecard=scorecard,
        name=f'{label} Metric',
        owner=user,
        goal_value=Decimal('10'),
        goal_direction=ScorecardMetric.DIR_ABOVE,
        metric_type=ScorecardMetric.TYPE_INTEGER,
    )
    return {'org': org, 'team': team, 'user': user, 'scorecard': scorecard, 'metric': metric}


class ScorecardCsvExportViewTest(TestCase):
    def setUp(self):
        self.fixtures = build_scorecard('Export')
        self.user = self.fixtures['user']
        self.scorecard = self.fixtures['scorecard']
        self.metric = self.fixtures['metric']
        self.periods = _build_periods(13, 'weekly')
        self.url = f'/scorecards/{self.scorecard.pk}/export/'

    def test_requires_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith('/accounts/login/'))

    def test_returns_csv_content_type(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp['Content-Type'].startswith('text/csv'))

    def test_header_row_includes_all_13_period_dates(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        content = resp.content.decode()
        header = content.splitlines()[0]
        for period in self.periods:
            self.assertIn(period.isoformat(), header)

    def test_entry_value_appears_in_correct_period_column(self):
        self.client.force_login(self.user)
        entered_period = self.periods[3]
        ScorecardEntry.objects.create(
            metric=self.metric, period_start=entered_period, value=Decimal('12'),
            entered_by=self.user,
        )
        resp = self.client.get(self.url)
        rows = resp.content.decode().splitlines()
        header_cells = rows[0].split(',')
        data_row = next(r for r in rows[1:] if self.metric.name in r)
        data_cells = data_row.split(',')

        col_index = header_cells.index(entered_period.isoformat())
        self.assertEqual(data_cells[col_index], self.metric.format_value(Decimal('12')))

    def test_period_with_no_entry_is_empty_cell_not_error(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        rows = resp.content.decode().splitlines()
        data_row = next(r for r in rows[1:] if self.metric.name in r)
        data_cells = data_row.split(',')
        # Metric, Owner, Goal + 13 period columns, all empty since no entries exist
        self.assertEqual(len(data_cells), 3 + len(self.periods))
        self.assertTrue(all(cell == '' for cell in data_cells[3:]))

    def test_cannot_export_another_organisations_scorecard(self):
        other = build_scorecard('Other')
        self.client.force_login(self.user)
        resp = self.client.get(f'/scorecards/{other["scorecard"].pk}/export/')
        self.assertEqual(resp.status_code, 404)
