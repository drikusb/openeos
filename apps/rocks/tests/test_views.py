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
