from datetime import date

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase

from apps.accounts.models import Membership, Organization, Team
from apps.accounts.scoping import SESSION_ORG_KEY, SESSION_TEAM_KEY
from apps.rocks.models import Rock


class MembershipModelTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Model Org')
        self.user = User.objects.create_user(username='modeluser', password='pw')

    def test_user_can_only_join_an_org_once(self):
        Membership.objects.create(user=self.user, organization=self.org)
        with self.assertRaises(IntegrityError):
            Membership.objects.create(user=self.user, organization=self.org)

    def test_is_admin_reflects_role(self):
        membership = Membership.objects.create(
            user=self.user, organization=self.org, role=Membership.ROLE_ADMIN
        )
        self.assertTrue(membership.is_admin())
        membership.role = Membership.ROLE_MEMBER
        self.assertFalse(membership.is_admin())


class TwoOrgMixin:
    """A user who is admin of Alpha and a plain member of Beta, each with one team and Rock."""

    def setUp(self):
        self.user = User.objects.create_user(username='switcher', password='pw')
        self.alpha = self._org('Alpha', Membership.ROLE_ADMIN)
        self.beta = self._org('Beta', Membership.ROLE_MEMBER)
        self.client.force_login(self.user)

    def _org(self, name, role):
        org = Organization.objects.create(name=f'{name} Org')
        team = Team.objects.create(organization=org, name=f'{name} Team')
        Membership.objects.create(user=self.user, organization=org, role=role)
        self.user.profile.teams.add(team)
        rock = Rock.objects.create(
            title=f'{name} Rock', owner=self.user, team=team,
            quarter=Rock.current_quarter(), year=Rock.current_year(), due_date=date.today(),
        )
        return {'org': org, 'team': team, 'rock': rock}

    def switch_to(self, org_fixture):
        return self.client.post(f'/org/{org_fixture["org"].pk}/switch/')


class OrgSwitchTest(TwoOrgMixin, TestCase):
    def test_first_org_by_name_is_active_by_default(self):
        resp = self.client.get('/')
        self.assertEqual(resp.context['active_org'], self.alpha['org'])
        self.assertEqual(resp.context['active_team'], self.alpha['team'])
        self.assertEqual(self.client.session[SESSION_ORG_KEY], self.alpha['org'].pk)

    def test_switch_changes_org_and_resets_team(self):
        self.client.get('/')
        self.assertEqual(self.client.session[SESSION_TEAM_KEY], self.alpha['team'].pk)

        resp = self.switch_to(self.beta)
        self.assertRedirects(resp, '/', fetch_redirect_response=False)
        self.assertEqual(self.client.session[SESSION_ORG_KEY], self.beta['org'].pk)
        self.assertNotIn(SESSION_TEAM_KEY, self.client.session)

        resp = self.client.get('/')
        self.assertEqual(resp.context['active_org'], self.beta['org'])
        self.assertEqual(resp.context['active_team'], self.beta['team'])

    def test_cannot_switch_to_org_without_membership(self):
        other = Organization.objects.create(name='Gamma Org')
        self.assertEqual(self.client.post(f'/org/{other.pk}/switch/').status_code, 404)

    def test_switch_is_post_only(self):
        self.assertEqual(self.client.get(f'/org/{self.beta["org"].pk}/switch/').status_code, 405)

    def test_stale_session_org_falls_back_to_first_membership(self):
        session = self.client.session
        session[SESSION_ORG_KEY] = 999999
        session.save()
        resp = self.client.get('/')
        self.assertEqual(resp.context['active_org'], self.alpha['org'])

    def test_team_switcher_only_accepts_teams_in_active_org(self):
        resp = self.client.post(f'/teams/{self.beta["team"].pk}/switch/')
        self.assertEqual(resp.status_code, 404)
        resp = self.client.post(f'/teams/{self.alpha["team"].pk}/switch/')
        self.assertEqual(resp.status_code, 302)

    def test_navbar_lists_both_orgs(self):
        resp = self.client.get('/')
        self.assertEqual(
            [o.pk for o in resp.context['user_orgs']],
            [self.alpha['org'].pk, self.beta['org'].pk],
        )
        self.assertContains(resp, f'/org/{self.beta["org"].pk}/switch/')


class ActiveOrgScopingTest(TwoOrgMixin, TestCase):
    def test_rock_list_follows_active_org(self):
        resp = self.client.get('/rocks/')
        self.assertContains(resp, 'Alpha Rock')
        self.assertNotContains(resp, 'Beta Rock')

        self.switch_to(self.beta)
        resp = self.client.get('/rocks/')
        self.assertContains(resp, 'Beta Rock')
        self.assertNotContains(resp, 'Alpha Rock')

    def test_pk_lookup_is_limited_to_active_org(self):
        self.assertEqual(self.client.get(f'/rocks/{self.beta["rock"].pk}/').status_code, 404)
        self.switch_to(self.beta)
        self.assertEqual(self.client.get(f'/rocks/{self.beta["rock"].pk}/').status_code, 200)
        self.assertEqual(self.client.get(f'/rocks/{self.alpha["rock"].pk}/').status_code, 404)

    def test_search_is_limited_to_active_org(self):
        resp = self.client.get('/search/', {'q': 'Rock'})
        self.assertContains(resp, 'Alpha Rock')
        self.assertNotContains(resp, 'Beta Rock')

    def test_vto_and_org_pages_follow_active_org(self):
        self.switch_to(self.beta)
        self.assertContains(self.client.get('/vto/'), 'Beta Org')
        self.assertContains(self.client.get('/org/'), 'Beta Org')
        self.assertContains(self.client.get('/teams/'), 'Beta Team')
        self.assertNotContains(self.client.get('/teams/'), 'Alpha Team')

    def test_profile_lists_every_membership(self):
        resp = self.client.get('/profile/')
        self.assertContains(resp, 'Alpha Org')
        self.assertContains(resp, 'Beta Org')


class PerOrgAdminTest(TwoOrgMixin, TestCase):
    def test_admin_rights_apply_only_in_that_org(self):
        self.assertEqual(self.client.get('/teams/new/').status_code, 200)
        self.assertEqual(self.client.get('/users/').status_code, 200)

        self.switch_to(self.beta)
        self.assertEqual(self.client.get('/teams/new/').status_code, 403)
        self.assertEqual(self.client.get('/users/').status_code, 403)

    def test_user_list_shows_only_teams_in_active_org(self):
        resp = self.client.get('/users/')
        self.assertContains(resp, 'Alpha Team')
        self.assertNotContains(resp, 'Beta Team')

    def test_rock_status_needs_owner_or_org_admin(self):
        other = User.objects.create_user(username='someoneelse', password='pw')
        Membership.objects.create(user=other, organization=self.alpha['org'])
        self.client.force_login(other)
        resp = self.client.post(
            f'/rocks/{self.alpha["rock"].pk}/status/', {'status': Rock.STATUS_OFF_TRACK}
        )
        self.assertEqual(resp.status_code, 403)

    def test_invite_creates_membership_in_active_org(self):
        resp = self.client.post('/users/invite/', {
            'username': 'invitee', 'email': 'invitee@example.com',
            'role': Membership.ROLE_MEMBER, 'teams': [self.alpha['team'].pk],
        })
        self.assertEqual(resp.status_code, 302)
        membership = Membership.objects.get(user__username='invitee')
        self.assertEqual(membership.organization, self.alpha['org'])
        self.assertIn(self.alpha['team'], membership.user.profile.teams.all())


class OrgSetupTest(TestCase):
    def test_first_user_sets_up_first_org_and_becomes_admin(self):
        user = User.objects.create_user(username='first', password='pw')
        self.client.force_login(user)
        resp = self.client.post('/org/setup/', {'name': 'First Org'})
        self.assertRedirects(resp, '/teams/new/', fetch_redirect_response=False)
        membership = Membership.objects.get(user=user)
        self.assertEqual(membership.organization.name, 'First Org')
        self.assertTrue(membership.is_admin())
        self.assertEqual(self.client.session[SESSION_ORG_KEY], membership.organization.pk)

    def test_superuser_can_add_another_org_and_is_switched_to_it(self):
        Organization.objects.create(name='Existing Org')
        root = User.objects.create_superuser(username='root', password='pw')
        self.client.force_login(root)
        resp = self.client.get('/org/setup/')
        self.assertContains(resp, 'New organisation')
        resp = self.client.post('/org/setup/', {'name': 'Client Org'})
        self.assertEqual(resp.status_code, 302)
        org = Organization.objects.get(name='Client Org')
        self.assertTrue(Membership.objects.filter(user=root, organization=org).exists())
        self.assertEqual(self.client.session[SESSION_ORG_KEY], org.pk)

    def test_regular_user_cannot_add_a_second_org(self):
        Organization.objects.create(name='Existing Org')
        user = User.objects.create_user(username='plain', password='pw')
        self.client.force_login(user)
        self.assertRedirects(self.client.get('/org/setup/'), '/', fetch_redirect_response=False)
        self.client.post('/org/setup/', {'name': 'Sneaky Org'})
        self.assertFalse(Organization.objects.filter(name='Sneaky Org').exists())
