from unittest.mock import patch

from django.core import mail
from django.db import connection
from django.db.utils import OperationalError
from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Membership, Organization, Team


class UserInviteEmailTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Invite Test Org')
        self.admin = User.objects.create_user(username='orgadmin', password='pw')
        Membership.objects.create(
            user=self.admin, organization=self.org, role=Membership.ROLE_ADMIN
        )
        self.team = Team.objects.create(organization=self.org, name='Invite Team')
        self.client.force_login(self.admin)

    def test_invite_sends_email_with_reset_link(self):
        resp = self.client.post('/users/invite/', {
            'username': 'newperson',
            'email': 'newperson@example.com',
            'first_name': 'New',
            'last_name': 'Person',
            'role': Membership.ROLE_MEMBER,
            'teams': [self.team.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['newperson@example.com'])
        self.assertIn('Invite Test Org', mail.outbox[0].subject)
        self.assertIn('/reset/', mail.outbox[0].body)

    def test_non_admin_cannot_invite(self):
        member = User.objects.create_user(username='plainmember', password='pw')
        Membership.objects.create(user=member, organization=self.org)
        self.client.force_login(member)
        resp = self.client.post('/users/invite/', {
            'username': 'blocked',
            'email': 'blocked@example.com',
            'role': Membership.ROLE_MEMBER,
        })
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)


class HealthzViewTest(TestCase):
    def test_anonymous_get_returns_ok(self):
        resp = self.client.get('/healthz/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'status': 'ok'})

    def test_database_outage_returns_503(self):
        with patch.object(connection, 'ensure_connection', side_effect=OperationalError('down')):
            resp = self.client.get('/healthz/')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json(), {'status': 'db-unavailable'})
