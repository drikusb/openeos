from datetime import date

from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Organization, Team
from apps.meetings.models import Meeting, MeetingNote, Headline, MeetingRating, SegueEntry


class MeetingPrintViewTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Print Org')
        self.team = Team.objects.create(organization=self.org, name='Print Team')
        self.user = User.objects.create_user(username='printuser', password='pw')
        self.user.profile.organization = self.org
        self.user.profile.teams.add(self.team)
        self.user.profile.save()
        self.meeting = Meeting.objects.create(
            team=self.team, scheduled_date=date.today(),
            status=Meeting.STATUS_ACTIVE, created_by=self.user,
        )

    def test_redirects_with_a_warning_when_the_meeting_is_not_complete(self):
        self.client.force_login(self.user)
        resp = self.client.get(f'/meetings/{self.meeting.pk}/print/')
        self.assertRedirects(resp, f'/meetings/{self.meeting.pk}/')

    def test_renders_the_meeting_s_notes_and_summary_once_complete(self):
        self.meeting.complete(cascading_messages='Tell the wider team about the new pricing.')
        MeetingNote.objects.create(meeting=self.meeting, segment=0, text='Everyone checked in well.')
        Headline.objects.create(
            meeting=self.meeting, author=self.user,
            headline_type=Headline.TYPE_GOOD, text='Closed the Acme deal',
        )
        MeetingRating.objects.create(meeting=self.meeting, participant=self.user, score=9)
        SegueEntry.objects.create(
            meeting=self.meeting, participant=self.user,
            personal_best='Ran a 10k', business_best='Shipped the release',
        )

        self.client.force_login(self.user)
        resp = self.client.get(f'/meetings/{self.meeting.pk}/print/')

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Everyone checked in well.')
        self.assertContains(resp, 'Closed the Acme deal')
        self.assertContains(resp, 'Tell the wider team about the new pricing.')
        self.assertContains(resp, '9/10')
        self.assertContains(resp, 'Ran a 10k')

    def test_print_colour_is_forced_on_so_headline_badges_keep_their_colour(self):
        """Browsers drop background colours when printing by default, which would
        otherwise strip the colour off the Good News / Bad News badges."""
        self.meeting.complete()
        self.client.force_login(self.user)
        resp = self.client.get(f'/meetings/{self.meeting.pk}/print/')
        self.assertContains(resp, 'print-color-adjust: exact')

    def test_export_button_only_shown_on_a_completed_meeting(self):
        self.client.force_login(self.user)
        resp_active = self.client.get(f'/meetings/{self.meeting.pk}/')
        self.assertNotContains(resp_active, 'Export PDF')

        self.meeting.complete()
        resp_complete = self.client.get(f'/meetings/{self.meeting.pk}/')
        self.assertContains(resp_complete, 'Export PDF')
