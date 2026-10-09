from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Membership, Organization, Team
from apps.issues.models import Issue


class IssueCompanyIssueFormPermissionTest(TestCase):
    """Only org admins can see or set is_company_issue (#5)."""

    def setUp(self):
        self.org = Organization.objects.create(name='Flag Org')
        self.team = Team.objects.create(organization=self.org, name='Flag Team')

        self.admin = User.objects.create_user(username='issueflagadmin', password='pw')
        Membership.objects.create(user=self.admin, organization=self.org, role=Membership.ROLE_ADMIN)
        self.admin.profile.teams.add(self.team)

        self.member = User.objects.create_user(username='issueflagmember', password='pw')
        Membership.objects.create(user=self.member, organization=self.org, role=Membership.ROLE_MEMBER)
        self.member.profile.teams.add(self.team)

        self.issue = Issue.objects.create(
            title='Existing Issue', originating_team=self.team, created_by=self.member,
        )

    def _issue_post_data(self, **overrides):
        data = {
            'title': 'An Issue',
            'description': '',
            'issue_type': Issue.TYPE_SHORT_TERM,
            'delegated_to_team': '',
            'linked_rocks': [],
            'target_quarter': '',
            'target_year': '',
        }
        data.update(overrides)
        return data

    def test_admin_sees_company_issue_checkbox_on_create(self):
        self.client.force_login(self.admin)
        resp = self.client.get('/issues/new/')
        self.assertContains(resp, 'is_company_issue')

    def test_member_does_not_see_company_issue_checkbox_on_create(self):
        self.client.force_login(self.member)
        resp = self.client.get('/issues/new/')
        self.assertNotContains(resp, 'is_company_issue')

    def test_admin_can_create_company_issue(self):
        self.client.force_login(self.admin)
        self.client.post('/issues/new/', self._issue_post_data(
            issue_type=Issue.TYPE_LONG_TERM, target_quarter=1, target_year=2026,
            is_company_issue='on',
        ))
        issue = Issue.objects.get(title='An Issue')
        self.assertTrue(issue.is_company_issue)

    def test_member_cannot_set_company_issue_via_post(self):
        """The field is absent from a non-admin's form, so posting it anyway is ignored."""
        self.client.force_login(self.member)
        self.client.post('/issues/new/', self._issue_post_data(is_company_issue='on'))
        issue = Issue.objects.get(title='An Issue')
        self.assertFalse(issue.is_company_issue)

    def test_admin_can_promote_existing_issue(self):
        self.client.force_login(self.admin)
        self.client.post(
            f'/issues/{self.issue.pk}/edit/',
            self._issue_post_data(
                title=self.issue.title, issue_type=Issue.TYPE_LONG_TERM,
                target_quarter=1, target_year=2026, is_company_issue='on',
            ),
        )
        self.issue.refresh_from_db()
        self.assertTrue(self.issue.is_company_issue)

    def test_member_cannot_promote_existing_issue_via_post(self):
        self.client.force_login(self.member)
        self.client.post(
            f'/issues/{self.issue.pk}/edit/',
            self._issue_post_data(title=self.issue.title, is_company_issue='on'),
        )
        self.issue.refresh_from_db()
        self.assertFalse(self.issue.is_company_issue)

    def test_member_editing_an_already_company_issue_does_not_demote_it(self):
        company_issue = Issue.objects.create(
            title='Already Company', originating_team=self.team, created_by=self.member,
            is_company_issue=True,
        )
        self.client.force_login(self.member)
        self.client.post(
            f'/issues/{company_issue.pk}/edit/',
            self._issue_post_data(title='Already Company (edited)'),
        )
        company_issue.refresh_from_db()
        self.assertEqual(company_issue.title, 'Already Company (edited)')
        self.assertTrue(company_issue.is_company_issue)

    def test_company_issue_flag_is_dropped_for_a_short_term_issue(self):
        """Company-wide only means anything for long-term issues, the VTO never shows
        short-term ones, so the flag shouldn't stick even if someone submits it anyway."""
        self.client.force_login(self.admin)
        self.client.post('/issues/new/', self._issue_post_data(
            issue_type=Issue.TYPE_SHORT_TERM, is_company_issue='on',
        ))
        issue = Issue.objects.get(title='An Issue')
        self.assertFalse(issue.is_company_issue)

    def test_demoting_a_long_term_issue_to_short_term_drops_the_company_flag(self):
        company_issue = Issue.objects.create(
            title='Was Long-term Company', originating_team=self.team, created_by=self.admin,
            issue_type=Issue.TYPE_LONG_TERM, is_company_issue=True,
            target_quarter=1, target_year=2026,
        )
        self.client.force_login(self.admin)
        self.client.post(
            f'/issues/{company_issue.pk}/edit/',
            self._issue_post_data(
                title=company_issue.title, issue_type=Issue.TYPE_SHORT_TERM,
                is_company_issue='on',
            ),
        )
        company_issue.refresh_from_db()
        self.assertFalse(company_issue.is_company_issue)
