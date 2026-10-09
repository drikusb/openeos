from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import Membership, Organization, Team
from apps.scorecards.models import Scorecard, ScorecardMetric


class MetricActiveCheckboxTest(TestCase):
    """A new metric must default to active, and show up on the scorecard (#27)."""

    def setUp(self):
        self.org = Organization.objects.create(name='Metric Org')
        self.team = Team.objects.create(organization=self.org, name='Metric Team')
        self.user = User.objects.create_user(username='metricuser', password='pw')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Membership.ROLE_ADMIN,
        )
        self.user.profile.teams.add(self.team)
        self.scorecard = Scorecard.objects.create(name='Weekly Scorecard', team=self.team)

    def _metric_post_data(self, **overrides):
        data = {
            'name': 'New Leads',
            'owner': self.user.pk,
            'metric_type': ScorecardMetric.TYPE_INTEGER,
            'goal_value': '10',
            'goal_direction': ScorecardMetric.DIR_ABOVE,
            'frequency': ScorecardMetric.FREQ_WEEKLY,
            'order': 0,
            'is_active': 'on',
        }
        data.update(overrides)
        return data

    def test_add_metric_form_renders_active_checkbox_checked_by_default(self):
        self.client.force_login(self.user)
        resp = self.client.get(f'/scorecards/{self.scorecard.pk}/metrics/add/')
        self.assertContains(resp, 'id_is_active')
        self.assertContains(resp, 'checked')

    def test_submitting_the_form_as_rendered_creates_an_active_metric(self):
        """A real browser submits is_active='on' because the checkbox defaults to checked."""
        self.client.force_login(self.user)
        self.client.post(
            f'/scorecards/{self.scorecard.pk}/metrics/add/', self._metric_post_data(),
        )
        metric = ScorecardMetric.objects.get(name='New Leads')
        self.assertTrue(metric.is_active)
        self.assertIn(metric, self.scorecard.active_metrics)

    def test_unchecking_active_creates_an_inactive_metric(self):
        self.client.force_login(self.user)
        data = self._metric_post_data()
        del data['is_active']
        self.client.post(f'/scorecards/{self.scorecard.pk}/metrics/add/', data)
        metric = ScorecardMetric.objects.get(name='New Leads')
        self.assertFalse(metric.is_active)

    def test_editing_an_inactive_metric_shows_the_checkbox_unchecked(self):
        metric = ScorecardMetric.objects.create(
            scorecard=self.scorecard, name='Dropped Metric', owner=self.user,
            goal_value=Decimal('5'), is_active=False,
        )
        self.client.force_login(self.user)
        resp = self.client.get(f'/scorecards/metric/{metric.pk}/edit/')
        self.assertNotContains(resp, 'checked')

    def test_editing_an_active_metric_and_resubmitting_keeps_it_active(self):
        metric = ScorecardMetric.objects.create(
            scorecard=self.scorecard, name='Existing Metric', owner=self.user,
            goal_value=Decimal('5'), is_active=True,
        )
        self.client.force_login(self.user)
        self.client.post(
            f'/scorecards/metric/{metric.pk}/edit/',
            self._metric_post_data(name='Existing Metric'),
        )
        metric.refresh_from_db()
        self.assertTrue(metric.is_active)
