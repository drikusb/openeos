from datetime import date, timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from apps.accounts.models import Organization, Team
from apps.rocks.models import Rock, RockCheckin


def make_rock(title='Test Rock', status=Rock.STATUS_ON_TRACK, **kwargs):
    org = Organization.objects.get_or_create(name='Test Org')[0]
    team = Team.objects.get_or_create(organization=org, name='Test Team')[0]
    user = User.objects.get_or_create(username='rockuser')[0]
    return Rock.objects.create(
        title=title, owner=user, team=team,
        quarter=1, year=2026, due_date=date(2026, 3, 31),
        status=status, **kwargs
    )


class RockStatusTest(TestCase):
    def setUp(self):
        self.rock = make_rock()

    def test_defaults_to_on_track(self):
        self.assertEqual(self.rock.status, Rock.STATUS_ON_TRACK)
        self.assertTrue(self.rock.is_on_track())
        self.assertFalse(self.rock.is_off_track())
        self.assertFalse(self.rock.is_complete())
        self.assertFalse(self.rock.is_dropped())
        self.assertTrue(self.rock.is_active())

    def test_off_track_helpers(self):
        self.rock.status = Rock.STATUS_OFF_TRACK
        self.assertFalse(self.rock.is_on_track())
        self.assertTrue(self.rock.is_off_track())
        self.assertTrue(self.rock.is_active())

    def test_complete_is_not_active(self):
        self.rock.status = Rock.STATUS_COMPLETE
        self.assertFalse(self.rock.is_active())
        self.assertTrue(self.rock.is_complete())

    def test_dropped_is_not_active(self):
        self.rock.status = Rock.STATUS_DROPPED
        self.assertFalse(self.rock.is_active())
        self.assertTrue(self.rock.is_dropped())

    def test_toggle_on_to_off(self):
        self.rock.toggle_track_status()
        self.assertEqual(self.rock.status, Rock.STATUS_OFF_TRACK)

    def test_toggle_off_to_on(self):
        self.rock.status = Rock.STATUS_OFF_TRACK
        self.rock.save()
        self.rock.toggle_track_status()
        self.assertEqual(self.rock.status, Rock.STATUS_ON_TRACK)

    def test_toggle_noop_when_complete(self):
        self.rock.status = Rock.STATUS_COMPLETE
        self.rock.save()
        self.rock.toggle_track_status()
        self.rock.refresh_from_db()
        self.assertEqual(self.rock.status, Rock.STATUS_COMPLETE)

    def test_toggle_noop_when_dropped(self):
        self.rock.status = Rock.STATUS_DROPPED
        self.rock.save()
        self.rock.toggle_track_status()
        self.rock.refresh_from_db()
        self.assertEqual(self.rock.status, Rock.STATUS_DROPPED)


class RockBadgeTest(TestCase):
    def setUp(self):
        self.rock = make_rock()

    def test_badge_on_track(self):
        self.assertEqual(self.rock.status_badge_class, 'success')

    def test_badge_off_track(self):
        self.rock.status = Rock.STATUS_OFF_TRACK
        self.assertEqual(self.rock.status_badge_class, 'danger')

    def test_badge_complete(self):
        self.rock.status = Rock.STATUS_COMPLETE
        self.assertEqual(self.rock.status_badge_class, 'secondary')

    def test_badge_dropped(self):
        self.rock.status = Rock.STATUS_DROPPED
        self.assertEqual(self.rock.status_badge_class, 'light text-dark border')

    def test_quarter_label(self):
        self.assertEqual(self.rock.quarter_label, 'Q1 2026')

    def test_str(self):
        self.assertEqual(str(self.rock), 'Test Rock')


class RockQuarterTest(TestCase):
    def test_current_quarter_in_range(self):
        q = Rock.current_quarter()
        self.assertIn(q, [1, 2, 3, 4])

    def test_current_year(self):
        self.assertEqual(Rock.current_year(), date.today().year)

    def test_quarter_boundaries(self):
        self.assertEqual((date(2026, 1, 1).month - 1) // 3 + 1, 1)
        self.assertEqual((date(2026, 4, 1).month - 1) // 3 + 1, 2)
        self.assertEqual((date(2026, 7, 1).month - 1) // 3 + 1, 3)
        self.assertEqual((date(2026, 10, 1).month - 1) // 3 + 1, 4)


class RockCheckinTest(TestCase):
    def setUp(self):
        self.rock = make_rock()
        self.user = self.rock.owner

    def test_not_overdue_when_freshly_created(self):
        self.assertFalse(self.rock.is_checkin_overdue)

    def test_overdue_when_rock_old_with_no_checkins(self):
        Rock.objects.filter(pk=self.rock.pk).update(
            created_at=timezone.now() - timedelta(days=8)
        )
        self.rock.refresh_from_db()
        self.assertTrue(self.rock.is_checkin_overdue)

    def test_not_overdue_when_recent_checkin_exists(self):
        Rock.objects.filter(pk=self.rock.pk).update(
            created_at=timezone.now() - timedelta(days=8)
        )
        self.rock.refresh_from_db()
        RockCheckin.objects.create(
            rock=self.rock, confidence=Rock.STATUS_ON_TRACK, created_by=self.user
        )
        self.assertFalse(self.rock.is_checkin_overdue)

    def test_overdue_when_latest_checkin_is_stale(self):
        checkin = RockCheckin.objects.create(
            rock=self.rock, confidence=Rock.STATUS_ON_TRACK, created_by=self.user
        )
        RockCheckin.objects.filter(pk=checkin.pk).update(
            created_at=timezone.now() - timedelta(days=8)
        )
        self.rock.refresh_from_db()
        self.assertTrue(self.rock.is_checkin_overdue)

    def test_not_overdue_when_complete(self):
        self.rock.status = Rock.STATUS_COMPLETE
        self.rock.save()
        Rock.objects.filter(pk=self.rock.pk).update(
            created_at=timezone.now() - timedelta(days=30)
        )
        self.rock.refresh_from_db()
        self.assertFalse(self.rock.is_checkin_overdue)

    def test_latest_checkin_returns_most_recent(self):
        older = RockCheckin.objects.create(
            rock=self.rock, confidence=Rock.STATUS_ON_TRACK, created_by=self.user
        )
        RockCheckin.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - timedelta(days=2)
        )
        newer = RockCheckin.objects.create(
            rock=self.rock, confidence=Rock.STATUS_OFF_TRACK, created_by=self.user
        )
        self.assertEqual(self.rock.latest_checkin, newer)

    def test_is_on_track_property(self):
        checkin = RockCheckin.objects.create(
            rock=self.rock, confidence=Rock.STATUS_OFF_TRACK, created_by=self.user
        )
        self.assertFalse(checkin.is_on_track)
