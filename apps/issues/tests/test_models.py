from django.test import TestCase
from django.contrib.auth.models import User
from apps.accounts.models import Organization, Team
from apps.issues.models import Issue, IssueActivity


def make_org_team():
    org = Organization.objects.get_or_create(name='Issue Org')[0]
    team = Team.objects.get_or_create(organization=org, name='Issue Team')[0]
    return org, team


def make_issue(title='Test Issue', status=Issue.STATUS_OPEN, issue_type=Issue.TYPE_SHORT_TERM, **kwargs):
    _, team = make_org_team()
    user = User.objects.get_or_create(username='issueuser')[0]
    return Issue.objects.create(
        title=title, originating_team=team, created_by=user,
        status=status, issue_type=issue_type, **kwargs
    )


class IssueStateTest(TestCase):
    def test_open_is_open(self):
        issue = make_issue(status=Issue.STATUS_OPEN)
        self.assertTrue(issue.is_open)
        self.assertFalse(issue.is_resolved)

    def test_in_ids_is_open(self):
        issue = make_issue(status=Issue.STATUS_IN_IDS)
        self.assertTrue(issue.is_open)

    def test_resolved_not_open(self):
        issue = make_issue(status=Issue.STATUS_RESOLVED)
        self.assertFalse(issue.is_open)
        self.assertTrue(issue.is_resolved)

    def test_dropped_not_open(self):
        issue = make_issue(status=Issue.STATUS_DROPPED)
        self.assertFalse(issue.is_open)
        self.assertFalse(issue.is_resolved)


class IssueDelegationTest(TestCase):
    def setUp(self):
        self.org, self.team = make_org_team()
        self.other_team = Team.objects.get_or_create(organization=self.org, name='Other Team')[0]
        self.issue = make_issue()

    def test_not_delegated_by_default(self):
        self.assertFalse(self.issue.is_delegated)
        self.assertEqual(self.issue.active_team, self.team)

    def test_delegated_active_team_is_delegate(self):
        self.issue.delegated_to_team = self.other_team
        self.assertTrue(self.issue.is_delegated)
        self.assertEqual(self.issue.active_team, self.other_team)


class IssueBadgeTest(TestCase):
    def test_status_badge_open(self):
        issue = make_issue(status=Issue.STATUS_OPEN)
        self.assertEqual(issue.status_badge_class, 'primary')

    def test_status_badge_in_ids(self):
        issue = make_issue(status=Issue.STATUS_IN_IDS)
        self.assertIn('warning', issue.status_badge_class)

    def test_status_badge_resolved(self):
        issue = make_issue(status=Issue.STATUS_RESOLVED)
        self.assertEqual(issue.status_badge_class, 'success')

    def test_type_badge_short_term(self):
        issue = make_issue(issue_type=Issue.TYPE_SHORT_TERM)
        self.assertIn('info', issue.type_badge_class)

    def test_type_badge_long_term(self):
        issue = make_issue(issue_type=Issue.TYPE_LONG_TERM)
        self.assertIn('purple', issue.type_badge_class)

    def test_str(self):
        issue = make_issue(title='My Issue')
        self.assertEqual(str(issue), 'My Issue')


class IssueActivityIconTest(TestCase):
    def setUp(self):
        self.issue = make_issue()
        self.user = User.objects.get_or_create(username='actuser')[0]

    def _make_activity(self, action):
        return IssueActivity.objects.create(
            issue=self.issue, actor=self.user, action=action
        )

    def test_icon_created(self):
        a = self._make_activity(IssueActivity.ACTION_CREATED)
        self.assertIsNotNone(a.icon)
        self.assertIn('bi-', a.icon)

    def test_icon_resolved(self):
        a = self._make_activity(IssueActivity.ACTION_RESOLVED)
        self.assertIn('bi-', a.icon)

    def test_icon_delegated(self):
        a = self._make_activity(IssueActivity.ACTION_DELEGATED)
        self.assertIn('bi-', a.icon)


class IssueIsCompanyIssueTest(TestCase):
    def test_defaults_to_false(self):
        issue = make_issue()
        self.assertFalse(issue.is_company_issue)

    def test_can_be_set_true(self):
        issue = make_issue(is_company_issue=True)
        self.assertTrue(issue.is_company_issue)
