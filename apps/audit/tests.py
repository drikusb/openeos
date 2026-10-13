from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import AnonymousUser, User
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Membership, Organization

from .admin import AuditEventAdmin
from .models import AuditEvent
from .services import record


def build_org(label):
    """Create an organisation with one admin and one plain member."""
    org = Organization.objects.create(name=f'{label} Org')
    admin = User.objects.create_user(username=f'{label.lower()}admin', password='pw')
    Membership.objects.create(user=admin, organization=org, role=Membership.ROLE_ADMIN)
    member = User.objects.create_user(username=f'{label.lower()}member', password='pw')
    Membership.objects.create(user=member, organization=org, role=Membership.ROLE_MEMBER)
    return {'org': org, 'admin': admin, 'member': member}


class RecordServiceTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.mine = build_org('Mine')

    def test_record_without_request(self):
        event = record('organization.exported', organization=self.mine['org'])
        self.assertIsInstance(event, AuditEvent)
        self.assertEqual(event.action, 'organization.exported')
        self.assertEqual(event.organization, self.mine['org'])
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_label, '')
        self.assertIsNone(event.ip_address)
        self.assertEqual(event.user_agent, '')
        self.assertEqual(event.details, {})
        self.assertEqual(AuditEvent.objects.count(), 1)

    def test_record_with_request_derives_actor_ip_and_user_agent(self):
        request = self.factory.get(
            '/', REMOTE_ADDR='10.0.0.9', HTTP_USER_AGENT='TestBrowser/1.0',
        )
        request.user = self.mine['admin']
        event = record('user.login', request=request)
        self.assertEqual(event.actor, self.mine['admin'])
        self.assertEqual(event.actor_label, 'mineadmin')
        self.assertEqual(event.ip_address, '10.0.0.9')
        self.assertEqual(event.user_agent, 'TestBrowser/1.0')

    def test_record_uses_first_forwarded_for_address(self):
        request = self.factory.get(
            '/', REMOTE_ADDR='10.0.0.9',
            HTTP_X_FORWARDED_FOR='203.0.113.5, 198.51.100.7',
        )
        request.user = AnonymousUser()
        event = record('user.login_failed', request=request)
        self.assertEqual(event.ip_address, '203.0.113.5')
        self.assertIsNone(event.actor)

    def test_record_ignores_an_unparseable_address(self):
        request = self.factory.get('/', HTTP_X_FORWARDED_FOR='not-an-ip')
        request.user = AnonymousUser()
        event = record('user.login_failed', request=request)
        self.assertIsNone(event.ip_address)

    def test_record_truncates_a_long_user_agent(self):
        request = self.factory.get('/', HTTP_USER_AGENT='x' * 400)
        request.user = AnonymousUser()
        event = record('user.login_failed', request=request)
        self.assertEqual(len(event.user_agent), 255)

    def test_explicit_actor_wins_over_request_user(self):
        request = self.factory.get('/')
        request.user = self.mine['member']
        event = record('user.logout', request=request, actor=self.mine['admin'])
        self.assertEqual(event.actor, self.mine['admin'])
        self.assertEqual(event.actor_label, 'mineadmin')

    def test_target_instance_is_described(self):
        org = self.mine['org']
        event = record('organization.exported', target=org, details={'format': 'json'})
        self.assertEqual(event.target_type, 'accounts.organization')
        self.assertEqual(event.target_id, str(org.pk))
        self.assertEqual(event.target_label, 'Mine Org')
        self.assertEqual(event.details, {'format': 'json'})

    def test_target_label_is_truncated(self):
        # Membership.__str__ joins the username and organisation name, so this
        # exceeds the 255-character target_label column.
        org = Organization.objects.create(name='L' * 255, slug='long-org')
        user = User.objects.create_user(username='u' * 150, password='pw')
        membership = Membership.objects.create(user=user, organization=org)
        self.assertGreater(len(str(membership)), 255)
        event = record('user.invited', target=membership)
        self.assertEqual(len(event.target_label), 255)
        self.assertEqual(event.target_type, 'accounts.membership')

    def test_actor_label_survives_user_deletion(self):
        event = record('user.login', actor=self.mine['member'])
        self.mine['member'].delete()
        event.refresh_from_db()
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_label, 'minemember')

    def test_record_never_raises(self):
        with mock.patch.object(
            AuditEvent.objects, 'create', side_effect=RuntimeError('db down')
        ):
            with self.assertLogs('apps.audit.services', level='ERROR') as logs:
                result = record('user.login')
        self.assertIsNone(result)
        self.assertIn('Could not record audit event', logs.output[0])


class AuthSignalTest(TestCase):
    def setUp(self):
        self.mine = build_org('Mine')

    def test_login_is_recorded(self):
        resp = self.client.post(
            '/accounts/login/', {'username': 'mineadmin', 'password': 'pw'},
            REMOTE_ADDR='192.0.2.10',
        )
        self.assertEqual(resp.status_code, 302)
        event = AuditEvent.objects.get(action='user.login')
        self.assertEqual(event.actor, self.mine['admin'])
        self.assertEqual(event.actor_label, 'mineadmin')
        self.assertEqual(event.ip_address, '192.0.2.10')
        self.assertEqual(event.organization, self.mine['org'])

    def test_failed_login_is_recorded_without_actor(self):
        resp = self.client.post(
            '/accounts/login/', {'username': 'mineadmin', 'password': 'wrong'},
        )
        self.assertEqual(resp.status_code, 200)
        event = AuditEvent.objects.get(action='user.login_failed')
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_label, '')
        self.assertEqual(event.details, {'username': 'mineadmin'})
        self.assertEqual(event.organization, self.mine['org'])
        self.assertFalse(AuditEvent.objects.filter(action='user.login').exists())

    def test_failed_login_for_unknown_username_has_no_organisation(self):
        self.client.post('/accounts/login/', {'username': 'nobody', 'password': 'wrong'})
        event = AuditEvent.objects.get(action='user.login_failed')
        self.assertIsNone(event.organization)
        self.assertEqual(event.details, {'username': 'nobody'})

    def test_logout_is_recorded(self):
        self.client.force_login(self.mine['admin'])
        resp = self.client.post('/accounts/logout/')
        self.assertEqual(resp.status_code, 302)
        event = AuditEvent.objects.get(action='user.logout')
        self.assertEqual(event.actor, self.mine['admin'])
        self.assertEqual(event.actor_label, 'mineadmin')
        self.assertEqual(event.organization, self.mine['org'])

    def test_member_of_several_organisations_is_attributed_to_the_active_one(self):
        theirs = build_org('Theirs')
        Membership.objects.create(
            user=self.mine['admin'], organization=theirs['org'], role=Membership.ROLE_MEMBER
        )
        # No session yet: the login cannot be pinned to either organisation.
        self.client.post('/accounts/login/', {'username': 'mineadmin', 'password': 'pw'})
        login = AuditEvent.objects.get(action='user.login')
        self.assertIsNone(login.organization)
        # Switching organisation pins the session, so the logout is attributed.
        self.client.post(f"/org/{theirs['org'].pk}/switch/")
        self.client.post('/accounts/logout/')
        logout = AuditEvent.objects.get(action='user.logout')
        self.assertEqual(logout.organization, theirs['org'])

    def test_login_events_show_on_the_organisations_audit_page(self):
        self.client.post('/accounts/login/', {'username': 'mineadmin', 'password': 'wrong'})
        self.client.post('/accounts/login/', {'username': 'mineadmin', 'password': 'pw'})
        resp = self.client.get('/org/audit/')
        self.assertEqual(resp.status_code, 200)
        actions = [e.action for e in resp.context['events']]
        self.assertEqual(sorted(actions), ['user.login', 'user.login_failed'])

    def test_logout_of_anonymous_session_is_not_recorded(self):
        resp = self.client.post('/accounts/logout/')
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(AuditEvent.objects.filter(action='user.logout').exists())


class AuditEventListViewTest(TestCase):
    def setUp(self):
        self.mine = build_org('Mine')
        self.theirs = build_org('Theirs')
        self.url = reverse('audit:event_list')
        record('organization.exported', organization=self.mine['org'], actor=self.mine['admin'])
        record('user.invited', organization=self.mine['org'], actor=self.mine['admin'])
        record('organization.exported', organization=self.theirs['org'], actor=self.theirs['admin'])

    def test_url(self):
        self.assertEqual(self.url, '/org/audit/')

    def test_anonymous_is_redirected_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp['Location'])

    def test_member_is_forbidden(self):
        self.client.force_login(self.mine['member'])
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_admin_sees_own_organisation_only(self):
        self.client.force_login(self.mine['admin'])
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'audit/event_list.html')
        events = list(resp.context['events'])
        # The two seeded events plus the admin's own login, which force_login records.
        self.assertEqual(len(events), 3)
        self.assertTrue(all(e.organization == self.mine['org'] for e in events))
        self.assertContains(resp, 'Mine Org')
        self.assertNotContains(resp, 'theirsadmin')

    def test_superuser_sees_active_organisation(self):
        root = User.objects.create_superuser(username='root', password='pw')
        Membership.objects.create(
            user=root, organization=self.theirs['org'], role=Membership.ROLE_MEMBER
        )
        self.client.force_login(root)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        events = list(resp.context['events'])
        # Their seeded export plus the superuser's own login (root is a member of Theirs only).
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e.organization == self.theirs['org'] for e in events))

    def test_user_without_organisation_is_sent_to_org_setup(self):
        orphan = User.objects.create_user(username='orphan', password='pw')
        self.client.force_login(orphan)
        resp = self.client.get(self.url)
        self.assertRedirects(resp, reverse('accounts:org_setup'), fetch_redirect_response=False)

    def test_action_filter(self):
        self.client.force_login(self.mine['admin'])
        resp = self.client.get(self.url, {'action': 'user.invited'})
        self.assertEqual(resp.status_code, 200)
        events = list(resp.context['events'])
        self.assertEqual([e.action for e in events], ['user.invited'])
        self.assertEqual(resp.context['selected_action'], 'user.invited')
        self.assertEqual(
            list(resp.context['actions']), ['organization.exported', 'user.invited', 'user.login']
        )

    def test_action_filter_with_no_matches_shows_empty_state(self):
        self.client.force_login(self.mine['admin'])
        resp = self.client.get(self.url, {'action': 'nothing.here'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['events']), 0)
        self.assertContains(resp, 'No events for this action')

    def test_pagination_keeps_the_action_filter(self):
        for _ in range(60):
            record('user.invited', organization=self.mine['org'], actor=self.mine['admin'])
        self.client.force_login(self.mine['admin'])
        resp = self.client.get(self.url, {'action': 'user.invited'})
        self.assertTrue(resp.context['is_paginated'])
        self.assertEqual(len(resp.context['events']), 50)
        self.assertContains(resp, '?page=2&amp;action=user.invited')
        resp = self.client.get(self.url, {'action': 'user.invited', 'page': 2})
        self.assertEqual(len(resp.context['events']), 11)


class OrganisationAdminCardTest(TestCase):
    """The Administration card on the organisation overview links to the log."""

    def setUp(self):
        self.mine = build_org('Mine')
        self.overview = reverse('accounts:org_detail')
        self.audit_url = reverse('audit:event_list')

    def test_admin_sees_the_card_on_the_org_overview(self):
        self.client.force_login(self.mine['admin'])
        resp = self.client.get(self.overview)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'audit/org_admin_card.html')
        self.assertContains(resp, 'Administration')
        self.assertContains(resp, 'Audit log')
        self.assertContains(resp, self.audit_url)

    def test_superuser_sees_the_card_on_the_org_overview(self):
        root = User.objects.create_superuser(username='root', password='pw')
        Membership.objects.create(
            user=root, organization=self.mine['org'], role=Membership.ROLE_MEMBER
        )
        self.client.force_login(root)
        resp = self.client.get(self.overview)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Administration')
        self.assertContains(resp, self.audit_url)

    def test_member_does_not_see_the_card(self):
        self.client.force_login(self.mine['member'])
        resp = self.client.get(self.overview)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Administration')
        self.assertNotContains(resp, self.audit_url)

    def test_user_list_no_longer_links_to_the_audit_log(self):
        self.client.force_login(self.mine['admin'])
        resp = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, self.audit_url)


class PruneAuditLogCommandTest(TestCase):
    def setUp(self):
        self.old = record('user.login')
        self.recent = record('user.logout')
        AuditEvent.objects.filter(pk=self.old.pk).update(
            created_at=timezone.now() - timedelta(days=400)
        )

    def test_prunes_events_older_than_default_year(self):
        out = StringIO()
        call_command('prune_audit_log', stdout=out)
        self.assertIn('Deleted 1 audit event(s) older than 365 day(s).', out.getvalue())
        self.assertFalse(AuditEvent.objects.filter(pk=self.old.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(pk=self.recent.pk).exists())

    def test_days_option(self):
        AuditEvent.objects.filter(pk=self.recent.pk).update(
            created_at=timezone.now() - timedelta(days=10)
        )
        out = StringIO()
        call_command('prune_audit_log', days=7, stdout=out)
        self.assertIn('Deleted 2 audit event(s) older than 7 day(s).', out.getvalue())
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_nothing_to_prune(self):
        out = StringIO()
        call_command('prune_audit_log', days=1000, stdout=out)
        self.assertIn('Deleted 0 audit event(s)', out.getvalue())
        self.assertEqual(AuditEvent.objects.count(), 2)


class AuditEventAdminTest(TestCase):
    def test_admin_is_read_only(self):
        model_admin = AuditEventAdmin(AuditEvent, AdminSite())
        request = RequestFactory().get('/admin/')
        request.user = User.objects.create_superuser(username='root', password='pw')
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertTrue(model_admin.has_view_permission(request))

    def test_superuser_can_open_the_admin_changelist(self):
        root = User.objects.create_superuser(username='root', password='pw')
        record('user.login', actor=root)
        self.client.force_login(root)
        resp = self.client.get(reverse('admin:audit_auditevent_changelist'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'user.login')
