from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Membership, Organization, Team
from apps.issues.models import Issue


class VTOCompanyIssuesTest(TestCase):
    """Only company-wide long-term Issues should appear on the VTO (#5)."""

    def setUp(self):
        self.org = Organization.objects.create(name='VTO Issues Org')
        self.other_org = Organization.objects.create(name='Other Issues Org')

        self.team_a = Team.objects.create(organization=self.org, name='Team A')
        self.team_b = Team.objects.create(organization=self.org, name='Team B')
        self.other_team = Team.objects.create(organization=self.other_org, name='Other Team')

        self.user = User.objects.create_user(username='vtoissueuser', password='pw')
        Membership.objects.create(user=self.user, organization=self.org)
        self.user.profile.teams.add(self.team_a)

        self.company_issue_a = Issue.objects.create(
            title='Company Issue A', originating_team=self.team_a,
            issue_type=Issue.TYPE_LONG_TERM, is_company_issue=True,
            target_quarter=1, target_year=2026,
        )
        self.company_issue_b = Issue.objects.create(
            title='Company Issue B', originating_team=self.team_b,
            issue_type=Issue.TYPE_LONG_TERM, is_company_issue=True,
            target_quarter=1, target_year=2026,
        )
        self.team_only_long_term = Issue.objects.create(
            title='Team-only Long-term Issue', originating_team=self.team_a,
            issue_type=Issue.TYPE_LONG_TERM, is_company_issue=False,
            target_quarter=1, target_year=2026,
        )
        self.company_short_term = Issue.objects.create(
            title='Company Short-term Issue', originating_team=self.team_a,
            issue_type=Issue.TYPE_SHORT_TERM, is_company_issue=True,
        )
        self.other_org_company_issue = Issue.objects.create(
            title='Other Org Company Issue', originating_team=self.other_team,
            issue_type=Issue.TYPE_LONG_TERM, is_company_issue=True,
            target_quarter=1, target_year=2026,
        )

    def test_vto_detail_lists_only_company_long_term_issues_for_the_active_org(self):
        self.client.force_login(self.user)
        resp = self.client.get('/vto/')
        issues = list(resp.context['long_term_issues'])
        self.assertIn(self.company_issue_a, issues)
        self.assertIn(self.company_issue_b, issues)
        self.assertNotIn(self.team_only_long_term, issues)
        self.assertNotIn(self.company_short_term, issues)
        self.assertNotIn(self.other_org_company_issue, issues)

    def test_vto_print_lists_only_company_long_term_issues_for_the_active_org(self):
        self.client.force_login(self.user)
        resp = self.client.get('/vto/print/')
        issues = list(resp.context['long_term_issues'])
        self.assertIn(self.company_issue_a, issues)
        self.assertIn(self.company_issue_b, issues)
        self.assertNotIn(self.team_only_long_term, issues)
        self.assertNotIn(self.company_short_term, issues)
        self.assertNotIn(self.other_org_company_issue, issues)

    def test_empty_state_mentions_company_wide(self):
        self.company_issue_a.delete()
        self.company_issue_b.delete()
        self.team_only_long_term.delete()
        self.company_short_term.delete()
        self.client.force_login(self.user)
        resp = self.client.get('/vto/')
        self.assertContains(resp, 'No company-wide long-term issues')
