from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Organization, Team


class ToDoFormDueDateRedisplayTest(TestCase):
    """Regression test: the due_date input used to render blank whenever the form
    redisplayed after any validation error, since the raw submitted string was being
    run back through the `date` filter, which silently returns '' for a non-date value."""

    def setUp(self):
        self.org = Organization.objects.create(name='Due Date Org')
        self.team = Team.objects.create(organization=self.org, name='Due Date Team')
        self.user = User.objects.create_user(username='duedateuser', password='pw')
        self.user.profile.organization = self.org
        self.user.profile.teams.add(self.team)
        self.user.profile.save()

    def test_redisplayed_form_after_validation_error_keeps_the_submitted_due_date(self):
        self.client.force_login(self.user)
        resp = self.client.post('/todos/new/', {
            'title': '',  # required field left blank, triggers a validation error
            'description': '',
            'owner': self.user.pk,
            'due_date': '2026-06-15',
            'linked_rock': '',
            'linked_issue': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'value="2026-06-15"')
