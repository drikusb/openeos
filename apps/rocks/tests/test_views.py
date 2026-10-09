from datetime import date

from django.core import mail
from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Membership, Organization, Team
from apps.rocks.models import Rock


class RockStatusOffTrackAlertTest(TestCase):
    def setUp(self):
        org = Organization.objects.create(name='Alert Org')
        self.team = Team.objects.create(organization=org, name='Alert Team')
        self.owner = User.objects.create_user(
            username='alertowner', email='owner@example.com', password='pw'
        )
        self.other = User.objects.create_user(
            username='alertother', email='other@example.com', password='pw'
        )
        for user in (self.owner, self.other):
            Membership.objects.create(user=user, organization=org)
        self.rock = Rock.objects.create(
            title='Ship it', owner=self.owner, team=self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31),
            status=Rock.STATUS_ON_TRACK,
        )

    def test_marking_off_track_sends_alert(self):
        self.client.force_login(self.owner)
        self.client.post(f'/rocks/{self.rock.pk}/status/', {'status': 'off_track'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Ship it', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, [self.owner.email])

    def test_repeated_off_track_does_not_resend(self):
        self.rock.status = Rock.STATUS_OFF_TRACK
        self.rock.save()
        self.client.force_login(self.owner)
        self.client.post(f'/rocks/{self.rock.pk}/status/', {'status': 'off_track'})
        self.assertEqual(len(mail.outbox), 0)

    def test_marking_on_track_does_not_send_alert(self):
        self.rock.status = Rock.STATUS_OFF_TRACK
        self.rock.save()
        self.client.force_login(self.owner)
        self.client.post(f'/rocks/{self.rock.pk}/status/', {'status': 'on_track'})
        self.assertEqual(len(mail.outbox), 0)

    def test_non_owner_forbidden_and_no_alert(self):
        self.client.force_login(self.other)
        resp = self.client.post(f'/rocks/{self.rock.pk}/status/', {'status': 'off_track'})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)


class RockCompanyRockFormPermissionTest(TestCase):
    """Only org admins can see or set is_company_rock (#3, #4)."""

    def setUp(self):
        self.org = Organization.objects.create(name='Flag Org')
        self.team = Team.objects.create(organization=self.org, name='Flag Team')

        self.admin = User.objects.create_user(username='flagadmin', password='pw')
        Membership.objects.create(
            user=self.admin, organization=self.org, role=Membership.ROLE_ADMIN
        )
        self.admin.profile.teams.add(self.team)

        self.member = User.objects.create_user(username='flagmember', password='pw')
        Membership.objects.create(
            user=self.member, organization=self.org, role=Membership.ROLE_MEMBER
        )
        self.member.profile.teams.add(self.team)

        self.rock = Rock.objects.create(
            title='Existing Rock', owner=self.member, team=self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31),
        )

    def _rock_post_data(self, **overrides):
        data = {
            'title': 'A Rock',
            'description': '',
            'owner': self.member.pk,
            'quarter': 1,
            'year': 2026,
            'due_date': '2026-03-31',
            'parent_rock': '',
        }
        data.update(overrides)
        return data

    def test_admin_sees_company_rock_checkbox_on_create(self):
        self.client.force_login(self.admin)
        resp = self.client.get('/rocks/new/')
        self.assertContains(resp, 'is_company_rock')

    def test_member_does_not_see_company_rock_checkbox_on_create(self):
        self.client.force_login(self.member)
        resp = self.client.get('/rocks/new/')
        self.assertNotContains(resp, 'is_company_rock')

    def test_admin_can_create_company_rock(self):
        self.client.force_login(self.admin)
        self.client.post('/rocks/new/', self._rock_post_data(is_company_rock='on'))
        rock = Rock.objects.get(title='A Rock')
        self.assertTrue(rock.is_company_rock)

    def test_member_cannot_set_company_rock_via_post(self):
        """The field is absent from a non-admin's form, so posting it anyway is ignored."""
        self.client.force_login(self.member)
        self.client.post('/rocks/new/', self._rock_post_data(is_company_rock='on'))
        rock = Rock.objects.get(title='A Rock')
        self.assertFalse(rock.is_company_rock)

    def test_admin_can_promote_existing_rock(self):
        self.client.force_login(self.admin)
        self.client.post(
            f'/rocks/{self.rock.pk}/edit/',
            self._rock_post_data(title=self.rock.title, is_company_rock='on'),
        )
        self.rock.refresh_from_db()
        self.assertTrue(self.rock.is_company_rock)

    def test_member_cannot_promote_existing_rock_via_post(self):
        self.client.force_login(self.member)
        self.client.post(
            f'/rocks/{self.rock.pk}/edit/',
            self._rock_post_data(title=self.rock.title, is_company_rock='on'),
        )
        self.rock.refresh_from_db()
        self.assertFalse(self.rock.is_company_rock)

    def test_member_editing_an_already_company_rock_does_not_demote_it(self):
        """is_company_rock is excluded from a non-admin's form entirely, so saving
        other fields must leave the Rock's existing flag untouched either way."""
        company_rock = Rock.objects.create(
            title='Already Company', owner=self.member, team=self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31), is_company_rock=True,
        )
        self.client.force_login(self.member)
        self.client.post(
            f'/rocks/{company_rock.pk}/edit/',
            self._rock_post_data(title='Already Company (edited)'),
        )
        company_rock.refresh_from_db()
        self.assertEqual(company_rock.title, 'Already Company (edited)')
        self.assertTrue(company_rock.is_company_rock)


class RockCompanyRockParentValidationTest(TestCase):
    """A company-wide Rock needs a company-wide parent, or none at all."""

    def setUp(self):
        self.org = Organization.objects.create(name='Nesting Org')
        self.team = Team.objects.create(organization=self.org, name='Nesting Team')

        self.admin = User.objects.create_user(username='nestadmin', password='pw')
        Membership.objects.create(
            user=self.admin, organization=self.org, role=Membership.ROLE_ADMIN
        )
        self.admin.profile.teams.add(self.team)

        self.member = User.objects.create_user(username='nestmember', password='pw')
        Membership.objects.create(
            user=self.member, organization=self.org, role=Membership.ROLE_MEMBER
        )
        self.member.profile.teams.add(self.team)

        self.company_parent = Rock.objects.create(
            title='Company Parent', owner=self.admin, team=self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31), is_company_rock=True,
        )
        self.team_parent = Rock.objects.create(
            title='Team Parent', owner=self.admin, team=self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31), is_company_rock=False,
        )

    def _rock_post_data(self, **overrides):
        data = {
            'title': 'Child Rock',
            'description': '',
            'owner': self.admin.pk,
            'quarter': 1,
            'year': 2026,
            'due_date': '2026-03-31',
            'parent_rock': '',
        }
        data.update(overrides)
        return data

    def test_company_rock_rejects_non_company_parent(self):
        self.client.force_login(self.admin)
        resp = self.client.post('/rocks/new/', self._rock_post_data(
            is_company_rock='on', parent_rock=self.team_parent.pk,
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(resp.context['form'], 'parent_rock',
                              'A company-wide Rock needs a company-wide parent, or no parent at all.')
        self.assertFalse(Rock.objects.filter(title='Child Rock').exists())

    def test_redisplayed_form_after_validation_error_keeps_the_submitted_due_date(self):
        """Regression test: the due_date input used to render blank whenever the form
        redisplayed after any validation error, since the raw submitted string was being
        run back through the `date` filter, which silently returns '' for a non-date value."""
        self.client.force_login(self.admin)
        resp = self.client.post('/rocks/new/', self._rock_post_data(
            is_company_rock='on', parent_rock=self.team_parent.pk, due_date='2026-06-15',
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'value="2026-06-15"')

    def test_company_rock_accepts_company_parent(self):
        self.client.force_login(self.admin)
        self.client.post('/rocks/new/', self._rock_post_data(
            is_company_rock='on', parent_rock=self.company_parent.pk,
        ))
        child = Rock.objects.get(title='Child Rock')
        self.assertTrue(child.is_company_rock)
        self.assertEqual(child.parent_rock, self.company_parent)

    def test_company_rock_accepts_no_parent(self):
        self.client.force_login(self.admin)
        self.client.post('/rocks/new/', self._rock_post_data(is_company_rock='on'))
        child = Rock.objects.get(title='Child Rock')
        self.assertTrue(child.is_company_rock)
        self.assertIsNone(child.parent_rock)

    def test_non_company_rock_accepts_non_company_parent(self):
        self.client.force_login(self.admin)
        self.client.post('/rocks/new/', self._rock_post_data(
            parent_rock=self.team_parent.pk,
        ))
        child = Rock.objects.get(title='Child Rock')
        self.assertFalse(child.is_company_rock)
        self.assertEqual(child.parent_rock, self.team_parent)

    def test_demoting_a_parent_with_company_children_requires_confirmation(self):
        child = Rock.objects.create(
            title='Company Child', owner=self.admin, team=self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31),
            is_company_rock=True, parent_rock=self.company_parent,
        )
        self.client.force_login(self.admin)
        resp = self.client.post(
            f'/rocks/{self.company_parent.pk}/edit/',
            self._rock_post_data(title=self.company_parent.title),  # is_company_rock omitted = unchecked
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(
            resp.context['form'], None,
            'Demoting this Rock will also remove company-wide status from '
            '1 child Rock: Company Child. Check "Also remove company-wide status '
            'from this Rock’s company-wide child Rocks" below and save again to confirm.'
        )
        self.company_parent.refresh_from_db()
        child.refresh_from_db()
        self.assertTrue(self.company_parent.is_company_rock)
        self.assertTrue(child.is_company_rock)

    def test_demoting_a_parent_with_confirmation_cascades_to_children(self):
        child = Rock.objects.create(
            title='Company Child', owner=self.admin, team=self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31),
            is_company_rock=True, parent_rock=self.company_parent,
        )
        other_child = Rock.objects.create(
            title='Team-only Child', owner=self.admin, team=self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31),
            is_company_rock=False, parent_rock=self.company_parent,
        )
        self.client.force_login(self.admin)
        resp = self.client.post(
            f'/rocks/{self.company_parent.pk}/edit/',
            self._rock_post_data(
                title=self.company_parent.title, confirm_demote_children='on',
            ),
        )
        self.assertEqual(resp.status_code, 302)
        self.company_parent.refresh_from_db()
        child.refresh_from_db()
        other_child.refresh_from_db()
        self.assertFalse(self.company_parent.is_company_rock)
        self.assertFalse(child.is_company_rock)
        self.assertFalse(other_child.is_company_rock)  # was already False, unaffected

    def test_demoting_a_parent_with_no_company_children_needs_no_confirmation(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            f'/rocks/{self.company_parent.pk}/edit/',
            self._rock_post_data(title=self.company_parent.title),  # is_company_rock omitted = unchecked
        )
        self.assertEqual(resp.status_code, 302)
        self.company_parent.refresh_from_db()
        self.assertFalse(self.company_parent.is_company_rock)

    def test_member_does_not_see_confirm_demote_checkbox(self):
        Rock.objects.create(
            title='Company Child', owner=self.admin, team=self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31),
            is_company_rock=True, parent_rock=self.company_parent,
        )
        self.client.force_login(self.member)
        resp = self.client.get(f'/rocks/{self.company_parent.pk}/edit/')
        self.assertNotContains(resp, 'confirm_demote_children')
