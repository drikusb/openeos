from datetime import date, timedelta

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Membership, Organization, Team
from apps.meetings.models import Meeting
from apps.todos.models import ToDo


class SendDailyNotificationsTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Cmd Org')
        self.team = Team.objects.create(organization=self.org, name='Cmd Team')
        self.user = User.objects.create_user(
            username='cronuser', email='cron@example.com', password='pw'
        )
        Membership.objects.create(user=self.user, organization=self.org)
        self.user.profile.teams.add(self.team)

    def test_sends_digest_for_overdue_todo(self):
        ToDo.objects.create(
            title='Late thing', owner=self.user, team=self.team,
            due_date=date.today() - timedelta(days=1),
        )
        call_command('send_daily_notifications')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Late thing', mail.outbox[0].body)

    def test_no_digest_for_todo_not_yet_due(self):
        ToDo.objects.create(
            title='Future thing', owner=self.user, team=self.team,
            due_date=date.today() + timedelta(days=1),
        )
        call_command('send_daily_notifications')
        self.assertEqual(len(mail.outbox), 0)

    def test_no_digest_for_completed_todo(self):
        todo = ToDo.objects.create(
            title='Done thing', owner=self.user, team=self.team,
            due_date=date.today() - timedelta(days=1),
        )
        todo.mark_complete()
        call_command('send_daily_notifications')
        self.assertEqual(len(mail.outbox), 0)

    def test_one_digest_per_owner_for_multiple_overdue_todos(self):
        ToDo.objects.create(title='A', owner=self.user, team=self.team, due_date=date.today() - timedelta(days=1))
        ToDo.objects.create(title='B', owner=self.user, team=self.team, due_date=date.today() - timedelta(days=2))
        call_command('send_daily_notifications')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('A', mail.outbox[0].body)
        self.assertIn('B', mail.outbox[0].body)

    def test_sends_reminder_for_meeting_scheduled_today(self):
        Meeting.objects.create(team=self.team, scheduled_date=date.today())
        call_command('send_daily_notifications')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Cmd Team', mail.outbox[0].subject)

    def test_no_reminder_for_meeting_scheduled_another_day(self):
        Meeting.objects.create(team=self.team, scheduled_date=date.today() + timedelta(days=1))
        call_command('send_daily_notifications')
        self.assertEqual(len(mail.outbox), 0)

    def test_no_reminder_for_completed_meeting_today(self):
        Meeting.objects.create(
            team=self.team, scheduled_date=date.today(), status=Meeting.STATUS_COMPLETE
        )
        call_command('send_daily_notifications')
        self.assertEqual(len(mail.outbox), 0)
