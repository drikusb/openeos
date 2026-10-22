"""Export of one organisation: what is collected, the archive, the view, the command."""
import csv
import io
import json
import shutil
import tempfile
import zipfile
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path

from unittest import mock

from django.apps import apps
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accountability.models import AccountabilityNode, AccountabilityRole
from apps.accounts.models import Membership, Organization, Team, UserProfile
from apps.accounts.portability import (
    EXCLUDED_MODELS, FORMAT_VERSION, PORTABLE_APPS, USER_FIELDS, ArchiveTooLarge,
    build_archive, collect, organization_lookup, portable_models,
)
from apps.accounts.portability import export
from apps.accounts.portability.export import label_for
from apps.audit.models import AuditEvent
from apps.issues.models import Issue, IssueActivity
from apps.meetings.models import Headline, Meeting, MeetingNote, MeetingRating, SegueEntry
from apps.notifications.models import NotificationPreference
from apps.rocks.models import Rock, RockCheckin, RockDependency, RockMilestone
from apps.scorecards.models import Scorecard, ScorecardEntry, ScorecardMetric
from apps.todos.models import ToDo
from apps.vto.models import VTO, VTOCoreValue, VTOSection, VTOSectionHistory, SectionKey

# The models populate_org() fills. collect() discovers what to export from the
# app registry, so on a tree with more models the archive carries more than
# these; the tests below only insist that these are present and populated.
POPULATED_MODELS = {
    'accounts.organization', 'accounts.team', 'auth.user', 'accounts.membership',
    'accounts.userprofile', 'notifications.notificationpreference',
    'vto.vto', 'vto.vtocorevalue', 'vto.vtosection', 'vto.vtosectionhistory',
    'accountability.accountabilitynode', 'accountability.accountabilityrole',
    'rocks.rock', 'rocks.rockmilestone', 'rocks.rockcheckin', 'rocks.rockdependency',
    'issues.issue', 'issues.issueactivity', 'todos.todo',
    'scorecards.scorecard', 'scorecards.scorecardmetric', 'scorecards.scorecardentry',
    'meetings.meeting', 'meetings.meetingnote', 'meetings.segueentry', 'meetings.headline',
    'meetings.meetingrating',
}

EDITED_AT = datetime(2026, 1, 2, 9, 30, tzinfo=dt_timezone.utc)


def populate_org(label):
    """Create an organisation with at least one record of every portable model.

    Three accounts: an admin (with an avatar, on both teams), a plain member,
    and a former member with no membership who still appears as the creator
    of an Issue. Records link across models (a To-Do to a Rock and an Issue, a
    Headline to an Issue, a child Rock to its parent, a child chart node to
    its parent) so a round trip has something to get wrong.
    """
    low = label.lower()
    org = Organization.objects.create(name=f'{label} Org')
    org.logo.save(f'{low}-logo.png', ContentFile(f'{label} logo bytes'.encode()), save=True)
    team = Team.objects.create(organization=org, name=f'{label} Leadership')
    team2 = Team.objects.create(organization=org, name=f'{label} Sales')

    admin = User.objects.create_user(
        username=f'{low}admin', password='pw', first_name=label, last_name='Admin',
        email=f'{low}admin@example.com',
    )
    member = User.objects.create_user(
        username=f'{low}member', password='pw', first_name=label, last_name='Member',
        email=f'{low}member@example.com',
    )
    former = User.objects.create_user(username=f'{low}former', password='pw')
    Membership.objects.create(user=admin, organization=org, role=Membership.ROLE_ADMIN)
    Membership.objects.create(user=member, organization=org, role=Membership.ROLE_MEMBER)
    admin.profile.teams.add(team, team2)
    admin.profile.avatar.save(
        f'{low}-avatar.png', ContentFile(f'{label} avatar bytes'.encode()), save=True
    )
    member.profile.teams.add(team)
    member.profile.avatar.save(
        f'{low}-member-avatar.png', ContentFile(f'{label} member avatar'.encode()), save=True
    )
    pref = NotificationPreference.for_user(admin)
    pref.overdue_todo_digest = False
    pref.save()
    pref = NotificationPreference.for_user(member)
    pref.meeting_reminders = False
    pref.save()

    vto = VTO.for_org(org)
    core_value = VTOCoreValue.objects.create(vto=vto, name=f'{label} Value', order=1)
    section = VTOSection.objects.create(
        vto=vto, key=SectionKey.TEN_YEAR_TARGET, content=f'{label} target',
        last_edited_by=admin, last_edited_at=EDITED_AT,
    )
    history = VTOSectionHistory.objects.create(
        section=section, content=f'{label} old target', edited_by=admin, edited_at=EDITED_AT,
    )

    node = AccountabilityNode.objects.create(
        organization=org, name=f'{label} Visionary', owner=admin, order=1,
    )
    child_node = AccountabilityNode.objects.create(
        organization=org, parent=node, name=f'{label} Integrator', order=2,
    )
    role = AccountabilityRole.objects.create(node=child_node, description=f'{label} LMA')

    rock = Rock.objects.create(
        title=f'{label} Rock', description='Done looks like done', owner=admin, team=team,
        quarter=1, year=2026, due_date=date(2026, 3, 31), status=Rock.STATUS_OFF_TRACK,
        created_by=admin,
    )
    child_rock = Rock.objects.create(
        title=f'{label} Child Rock', owner=member, team=team2, quarter=1, year=2026,
        due_date=date(2026, 3, 31), parent_rock=rock, created_by=admin,
    )
    milestone = RockMilestone.objects.create(rock=rock, title=f'{label} Milestone', order=1)
    checkin = RockCheckin.objects.create(
        rock=rock, confidence=Rock.STATUS_OFF_TRACK, note=f'{label} slipping', created_by=admin,
    )
    dependency = RockDependency.objects.create(
        rock=child_rock, depends_on_rock=rock, description='Needs the parent first',
    )

    issue = Issue.objects.create(
        title=f'{label} Issue', originating_team=team, created_by=former,
        delegated_to_team=team2, issue_type=Issue.TYPE_LONG_TERM, target_quarter=2,
        target_year=2026,
    )
    issue.linked_rocks.add(rock)
    activity = IssueActivity.objects.create(
        issue=issue, actor=admin, action=IssueActivity.ACTION_COMMENT, notes=f'{label} note',
    )

    todo = ToDo.objects.create(
        title=f'{label} To-Do', owner=member, team=team, due_date=date(2026, 2, 1),
        linked_rock=rock, linked_issue=issue,
    )

    scorecard = Scorecard.objects.create(name=f'{label} Scorecard', team=team)
    metric = ScorecardMetric.objects.create(
        scorecard=scorecard, name=f'{label} Metric', owner=admin, goal_value=Decimal('10.5'),
        goal_direction=ScorecardMetric.DIR_BELOW,
    )
    entry = ScorecardEntry.objects.create(
        metric=metric, period_start=date(2026, 1, 5), value=Decimal('7.25'), entered_by=member,
        notes='quiet week',
    )

    meeting = Meeting.objects.create(
        team=team, scheduled_date=date(2026, 1, 5), status=Meeting.STATUS_COMPLETE,
        started_at=EDITED_AT, cascading_messages=f'{label} cascade', created_by=admin,
    )
    note = MeetingNote.objects.create(
        meeting=meeting, segment=5, text=f'{label} IDS notes', updated_by=admin,
    )
    segue = SegueEntry.objects.create(
        meeting=meeting, participant=admin, personal_best='Slept', business_best='Shipped',
    )
    headline = Headline.objects.create(
        meeting=meeting, author=member, text=f'{label} headline', escalated_issue=issue,
    )
    rating = MeetingRating.objects.create(meeting=meeting, participant=member, score=9)

    return {
        'org': org, 'team': team, 'team2': team2, 'admin': admin, 'member': member,
        'former': former, 'vto': vto, 'core_value': core_value, 'section': section,
        'history': history, 'node': node, 'child_node': child_node, 'role': role,
        'rock': rock, 'child_rock': child_rock, 'milestone': milestone, 'checkin': checkin,
        'dependency': dependency, 'issue': issue, 'activity': activity, 'todo': todo,
        'scorecard': scorecard, 'metric': metric, 'entry': entry, 'meeting': meeting,
        'note': note, 'segue': segue, 'headline': headline, 'rating': rating,
    }


class MediaRootMixin:
    """Point MEDIA_ROOT at a fresh directory so uploads never touch the real one.

    The build-info lookup is pointed into the same directory, where no file
    exists until a test writes one, so the manifest does not depend on
    whether the checkout running the tests has a BUILD_INFO file.
    """

    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp(prefix='openeos-media-')
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        self.build_info = Path(self.media_root, 'BUILD_INFO')
        patcher = mock.patch.object(export, 'BUILD_INFO_PATH', self.build_info)
        patcher.start()
        self.addCleanup(patcher.stop)


def export_to_bytes(org, **kwargs):
    buffer = io.BytesIO()
    manifest = build_archive(org, fileobj=buffer, **kwargs)
    return buffer.getvalue(), manifest


class CollectTest(MediaRootMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.a = populate_org('Alpha')
        self.b = populate_org('Beta')

    def test_every_model_in_the_portable_apps_is_collected_or_excluded(self):
        registered = {
            label_for(model)
            for app_label in PORTABLE_APPS
            for model in apps.get_app_config(app_label).get_models()
        }
        collected = collect(self.a['org'])
        self.assertEqual(registered - set(collected), set(EXCLUDED_MODELS))
        self.assertEqual(set(collected) - registered, {'auth.user'})
        self.assertTrue(POPULATED_MODELS <= set(collected))
        self.assertNotIn('audit.auditevent', collected)

    def test_order_puts_every_parent_before_its_children_and_is_deterministic(self):
        ordered = portable_models()
        self.assertEqual([label_for(m) for m in ordered], list(collect(self.a['org'])))
        self.assertEqual(ordered, portable_models())
        self.assertEqual(ordered[0], Organization)
        seen = set()
        for model in ordered:
            fields = list(model._meta.concrete_fields) + list(model._meta.many_to_many)
            for field in fields:
                target = getattr(field, 'related_model', None)
                if field.is_relation and target in ordered and target is not model:
                    with self.subTest(model=label_for(model), field=field.name):
                        self.assertIn(target, seen)
            seen.add(model)
        # Self-references do not hold a model back: Rock comes once, before its children.
        self.assertEqual(ordered.count(Rock), 1)
        self.assertLess(ordered.index(Rock), ordered.index(RockMilestone))
        self.assertLess(ordered.index(Rock), ordered.index(Issue))  # Issue.linked_rocks
        self.assertLess(ordered.index(Team), ordered.index(UserProfile))  # profile.teams

    def test_lookup_prefers_a_required_path_then_the_shortest_then_the_first_field(self):
        self.assertEqual(organization_lookup(Organization), '')
        self.assertEqual(organization_lookup(Team), 'organization')
        self.assertEqual(organization_lookup(VTO), 'organization')
        self.assertEqual(organization_lookup(AccountabilityRole), 'node__organization')
        self.assertEqual(organization_lookup(RockMilestone), 'rock__team__organization')
        self.assertEqual(organization_lookup(ScorecardEntry),
                         'metric__scorecard__team__organization')
        # The required originating team wins over the optional delegated team.
        self.assertEqual(organization_lookup(Issue), 'originating_team__organization')
        # Headline's required meeting wins over its optional escalated issue.
        self.assertEqual(organization_lookup(Headline), 'meeting__team__organization')
        # To-Do's own team wins over the longer route through a linked Rock.
        self.assertEqual(organization_lookup(ToDo), 'team__organization')
        # Two required paths of the same length: the field declared first wins.
        self.assertEqual(organization_lookup(RockDependency), 'rock__team__organization')
        self.assertIsNone(organization_lookup(User))
        self.assertIsNone(organization_lookup(NotificationPreference))

    def test_model_reached_through_two_steps_is_scoped_to_its_organisation(self):
        extra = RockMilestone.objects.create(
            rock=self.b['child_rock'], title='Beta milestone on a second team', order=2
        )
        mine = set(collect(self.a['org'])['rocks.rockmilestone'])
        theirs = set(collect(self.b['org'])['rocks.rockmilestone'])
        self.assertEqual(mine, {self.a['milestone']})
        self.assertEqual(theirs, {self.b['milestone'], extra})

    def test_every_queryset_has_data_and_nothing_from_the_other_organisation(self):
        mine = collect(self.a['org'])
        theirs = collect(self.b['org'])
        for label, queryset in mine.items():
            with self.subTest(label=label):
                my_pks = set(queryset.values_list('pk', flat=True))
                their_pks = set(theirs[label].values_list('pk', flat=True))
                everything = set(queryset.model._default_manager.values_list('pk', flat=True))
                if label in POPULATED_MODELS:
                    self.assertTrue(my_pks, 'populate_org left this model empty')
                self.assertEqual(my_pks & their_pks, set())
                self.assertEqual(my_pks | their_pks, everything)

    def test_users_are_members_plus_anyone_a_record_still_refers_to(self):
        users = set(collect(self.a['org'])['auth.user'].values_list('username', flat=True))
        self.assertEqual(users, {'alphaadmin', 'alphamember', 'alphaformer'})


class BuildArchiveTest(MediaRootMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.a = populate_org('Alpha')
        self.b = populate_org('Beta')
        self.a['admin'].profile.teams.add(self.b['team'])  # on a team of another organisation
        self.blob, self.manifest = export_to_bytes(
            self.a['org'], exported_by=self.a['admin'], via='web'
        )
        self.archive = zipfile.ZipFile(io.BytesIO(self.blob))

    def names(self):
        return set(self.archive.namelist())

    def everything(self):
        """Every entry decompressed, so text searches see the data not the deflate stream."""
        return '\n'.join(self.archive.read(n).decode('latin-1') for n in self.archive.namelist())

    def test_manifest(self):
        manifest = json.loads(self.archive.read('manifest.json'))
        self.assertEqual(manifest, json.loads(json.dumps(self.manifest)))
        self.assertEqual(manifest['format_version'], FORMAT_VERSION)
        self.assertEqual(manifest['exported_by'], 'alphaadmin')
        self.assertEqual(manifest['via'], 'web')
        self.assertTrue(manifest['exported_at'].endswith('+00:00'))
        self.assertEqual(manifest['organization'], {
            'id': self.a['org'].pk, 'name': 'Alpha Org', 'slug': 'alpha-org',
        })
        self.assertIn('django', manifest['app'])
        self.assertIsNone(manifest['app']['openeos_build'])
        collected = collect(self.a['org'])
        self.assertEqual(list(manifest['record_counts']), list(collected))
        self.assertTrue(POPULATED_MODELS <= set(manifest['record_counts']))
        expected = {label: qs.count() for label, qs in collected.items()}
        self.assertEqual(manifest['record_counts'], expected)
        self.assertEqual(manifest['record_counts']['rocks.rock'], 2)
        self.assertEqual(manifest['record_counts']['auth.user'], 3)
        self.assertEqual(sorted(manifest['files']), [
            'avatars/alpha-avatar.png', 'avatars/alpha-member-avatar.png',
            'org_logos/alpha-logo.png',
        ])

    def test_build_id_comes_from_the_first_line_of_build_info(self):
        self.assertIsNone(export._build_id())
        self.build_info.write_text('2026.10.09-abc123\nbuilt on ci\n', encoding='utf-8')
        self.assertEqual(export._build_id(), '2026.10.09-abc123')
        self.assertEqual(export._build_id(Path(self.media_root, 'nope')), None)
        _, manifest = export_to_bytes(self.a['org'])
        self.assertEqual(manifest['app']['openeos_build'], '2026.10.09-abc123')
        self.build_info.write_text('  \n', encoding='utf-8')
        self.assertIsNone(export._build_id())

    def test_layout(self):
        names = self.names()
        self.assertIn('README.txt', names)
        for label in collect(self.a['org']):
            self.assertIn(f'data/{label}.json', names)
            self.assertIn(f'csv/{label.split(".")[1]}.csv', names)
        readme = self.archive.read('README.txt').decode()
        self.assertIn('python manage.py import_organization', readme)
        self.assertIn('Alpha Org', readme)
        self.assertIn('(unknown)', readme)

    def test_user_json_carries_no_secrets(self):
        users = json.loads(self.archive.read('data/auth.user.json'))
        self.assertEqual(len(users), 3)
        for record in users:
            self.assertEqual(record['model'], 'auth.user')
            self.assertEqual(set(record['fields']), set(USER_FIELDS))
        admin = next(u for u in users if u['fields']['username'] == 'alphaadmin')
        self.assertEqual(admin['pk'], self.a['admin'].pk)
        self.assertEqual(admin['fields']['email'], 'alphaadmin@example.com')
        self.assertNotIn('pbkdf2', self.archive.read('data/auth.user.json').decode())
        self.assertNotIn(self.a['admin'].password, self.everything())
        self.assertNotIn('is_superuser', self.everything())

    def test_json_is_django_serializer_shaped_with_plain_pks(self):
        rocks = json.loads(self.archive.read('data/rocks.rock.json'))
        child = next(r for r in rocks if r['fields']['title'] == 'Alpha Child Rock')
        self.assertEqual(child['model'], 'rocks.rock')
        self.assertEqual(child['pk'], self.a['child_rock'].pk)
        self.assertEqual(child['fields']['parent_rock'], self.a['rock'].pk)
        self.assertEqual(child['fields']['owner'], self.a['member'].pk)
        self.assertEqual(child['fields']['due_date'], '2026-03-31')
        issues = json.loads(self.archive.read('data/issues.issue.json'))
        self.assertEqual(issues[0]['fields']['linked_rocks'], [self.a['rock'].pk])

    def test_profile_teams_are_limited_to_this_organisation(self):
        profiles = json.loads(self.archive.read('data/accounts.userprofile.json'))
        admin = next(p for p in profiles if p['fields']['user'] == self.a['admin'].pk)
        self.assertEqual(
            sorted(admin['fields']['teams']), sorted([self.a['team'].pk, self.a['team2'].pk])
        )

    def test_nothing_from_the_other_organisation(self):
        self.assertNotIn('Beta', self.everything())
        self.assertNotIn('beta', self.everything())

    def test_media_included_when_present(self):
        self.assertEqual(
            self.archive.read('media/org_logos/alpha-logo.png'), b'Alpha logo bytes'
        )
        self.assertEqual(
            self.archive.read('media/avatars/alpha-avatar.png'), b'Alpha avatar bytes'
        )
        self.assertNotIn('media/org_logos/beta-logo.png', self.names())

    def test_missing_media_file_is_skipped(self):
        Path(self.media_root, 'org_logos', 'alpha-logo.png').unlink()
        blob, manifest = export_to_bytes(self.a['org'])
        self.assertEqual(
            manifest['files'], ['avatars/alpha-avatar.png', 'avatars/alpha-member-avatar.png']
        )
        names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
        self.assertNotIn('media/org_logos/alpha-logo.png', names)

    def test_csv_has_headers_and_renders_foreign_keys_twice(self):
        rows = list(csv.reader(io.StringIO(self.archive.read('csv/todo.csv').decode())))
        header, data = rows[0], rows[1:]
        self.assertEqual(len(data), 1)
        for column in ('id', 'title', 'due_date', 'owner', 'owner_id', 'team', 'team_id',
                       'linked_rock', 'linked_rock_id', 'linked_issue', 'linked_issue_id'):
            self.assertIn(column, header)
        row = dict(zip(header, data[0]))
        self.assertEqual(row['title'], 'Alpha To-Do')
        self.assertEqual(row['due_date'], '2026-02-01')
        self.assertEqual(row['owner'], 'alphamember')
        self.assertEqual(row['owner_id'], str(self.a['member'].pk))
        self.assertEqual(row['linked_rock'], 'Alpha Rock')
        self.assertEqual(row['linked_rock_id'], str(self.a['rock'].pk))

        rows = list(csv.reader(io.StringIO(self.archive.read('csv/issue.csv').decode())))
        row = dict(zip(rows[0], rows[1]))
        self.assertEqual(row['linked_rocks'], 'Alpha Rock')
        self.assertEqual(row['linked_rocks_ids'], str(self.a['rock'].pk))
        self.assertEqual(row['created_by'], 'alphaformer')

        rows = list(csv.reader(io.StringIO(self.archive.read('csv/user.csv').decode())))
        self.assertEqual(rows[0], ['id', *USER_FIELDS])
        self.assertNotIn('password', rows[0])

    def test_size_guard(self):
        with self.assertRaises(ArchiveTooLarge):
            build_archive(self.a['org'], fileobj=io.BytesIO(), max_bytes=200)
        buffer = io.BytesIO()
        build_archive(self.a['org'], fileobj=buffer, max_bytes=10 * 1024 * 1024)
        self.assertGreater(len(buffer.getvalue()), 200)


class OrganizationExportViewTest(MediaRootMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.a = populate_org('Alpha')
        self.url = reverse('accounts:org_export')

    def test_url(self):
        self.assertEqual(self.url, '/org/export/')

    def test_anonymous_is_redirected_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp['Location'])

    def test_member_is_forbidden(self):
        self.client.force_login(self.a['member'])
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {'password': 'pw'}).status_code, 403)

    def test_user_without_organisation_is_sent_to_org_setup(self):
        root = User.objects.create_superuser(username='root', password='pw')
        self.client.force_login(root)
        resp = self.client.get(self.url)
        self.assertRedirects(resp, reverse('accounts:org_setup'), fetch_redirect_response=False)

    def test_admin_sees_the_form_and_the_counts(self):
        self.client.force_login(self.a['admin'])
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'accounts/org_export.html')
        self.assertContains(resp, 'Alpha Org')
        self.assertContains(resp, 'name="password"')
        self.assertContains(resp, 'export_organization alpha-org')
        self.assertIn(('Rocks', 2), resp.context['record_counts'])

    def test_wrong_password_shows_an_error_and_records_nothing(self):
        self.client.force_login(self.a['admin'])
        resp = self.client.post(self.url, {'password': 'nope'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'].split(';')[0], 'text/html')
        self.assertContains(resp, 'That password is not right')
        self.assertFalse(AuditEvent.objects.filter(action='organization.exported').exists())

    def test_right_password_downloads_the_archive_and_records_it(self):
        self.client.force_login(self.a['admin'])
        resp = self.client.post(self.url, {'password': 'pw'}, REMOTE_ADDR='192.0.2.4')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/zip')
        disposition = resp['Content-Disposition']
        self.assertTrue(disposition.startswith('attachment; filename="openeos-export-alpha-org-'))
        self.assertTrue(disposition.endswith('Z.zip"'))
        blob = b''.join(resp.streaming_content)
        archive = zipfile.ZipFile(io.BytesIO(blob))
        manifest = json.loads(archive.read('manifest.json'))
        self.assertEqual(manifest['exported_by'], 'alphaadmin')
        self.assertEqual(manifest['via'], 'web')

        event = AuditEvent.objects.get(action='organization.exported')
        self.assertEqual(event.actor, self.a['admin'])
        self.assertEqual(event.organization, self.a['org'])
        self.assertEqual(event.target_type, 'accounts.organization')
        self.assertEqual(event.target_id, str(self.a['org'].pk))
        self.assertEqual(event.ip_address, '192.0.2.4')
        self.assertEqual(event.details['format_version'], FORMAT_VERSION)
        self.assertEqual(event.details['via'], 'web')
        self.assertEqual(event.details['size_bytes'], len(blob))
        self.assertEqual(event.details['record_counts'], manifest['record_counts'])

    def test_superuser_member_can_export(self):
        root = User.objects.create_superuser(username='root', password='pw')
        Membership.objects.create(user=root, organization=self.a['org'])
        self.client.force_login(root)
        resp = self.client.post(self.url, {'password': 'pw'})
        self.assertEqual(resp['Content-Type'], 'application/zip')

    @override_settings(EXPORT_MAX_BYTES=100)
    def test_archive_over_the_limit_is_refused_with_the_command_named(self):
        self.client.force_login(self.a['admin'])
        resp = self.client.post(self.url, {'password': 'pw'})
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'accounts/org_export.html')
        self.assertContains(resp, 'export_organization alpha-org')
        self.assertContains(resp, 'larger than the 0 MB limit')
        self.assertFalse(AuditEvent.objects.filter(action='organization.exported').exists())

    def test_admin_sees_the_export_link_on_the_org_overview(self):
        self.client.force_login(self.a['admin'])
        resp = self.client.get(reverse('accounts:org_detail'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Export data')
        self.assertContains(resp, self.url)

    def test_member_does_not_see_the_export_link_on_the_org_overview(self):
        self.client.force_login(self.a['member'])
        resp = self.client.get(reverse('accounts:org_detail'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, self.url)

    def test_user_list_does_not_link_to_the_export(self):
        self.client.force_login(self.a['admin'])
        resp = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, self.url)


class ExportOrganizationCommandTest(MediaRootMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.a = populate_org('Alpha')
        self.b = populate_org('Beta')
        self.out = tempfile.mkdtemp(prefix='openeos-export-')
        self.addCleanup(shutil.rmtree, self.out, ignore_errors=True)

    def test_one_slug(self):
        stdout = StringIO()
        call_command('export_organization', 'alpha-org', '--out', self.out, stdout=stdout)
        files = sorted(Path(self.out).iterdir())
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.startswith('openeos-export-alpha-org-'))
        self.assertEqual(stdout.getvalue().strip(), str(files[0]))
        manifest = json.loads(zipfile.ZipFile(files[0]).read('manifest.json'))
        self.assertEqual(manifest['via'], 'command')
        self.assertIsNone(manifest['exported_by'])
        self.assertEqual(manifest['organization']['slug'], 'alpha-org')

        event = AuditEvent.objects.get(action='organization.exported')
        self.assertIsNone(event.actor)
        self.assertEqual(event.organization, self.a['org'])
        self.assertEqual(event.details['via'], 'command')
        self.assertEqual(event.details['size_bytes'], files[0].stat().st_size)
        self.assertEqual(event.details['record_counts'], manifest['record_counts'])

    def test_all(self):
        stdout = StringIO()
        call_command('export_organization', '--all', '--out', self.out, stdout=stdout)
        archives = sorted(Path(self.out).glob('openeos-export-*.zip'))
        self.assertEqual(len(archives), 2)
        index = json.loads(Path(self.out, 'instance-manifest.json').read_text())
        self.assertEqual(index['format_version'], FORMAT_VERSION)
        self.assertEqual([a['slug'] for a in index['archives']], ['alpha-org', 'beta-org'])
        for entry, archive in zip(index['archives'], archives):
            self.assertEqual(entry['file'], archive.name)
            self.assertEqual(entry['size_bytes'], archive.stat().st_size)
            self.assertEqual(entry['record_counts']['rocks.rock'], 2)
        self.assertEqual(AuditEvent.objects.filter(action='organization.exported').count(), 2)
        for line in [str(a) for a in archives] + [str(Path(self.out, 'instance-manifest.json'))]:
            self.assertIn(line, stdout.getvalue())

    def test_bad_arguments(self):
        with self.assertRaisesMessage(CommandError, 'No organisation has the slug "nope"'):
            call_command('export_organization', 'nope', '--out', self.out)
        with self.assertRaisesMessage(CommandError, 'either an organisation slug or --all'):
            call_command('export_organization', '--out', self.out)
        with self.assertRaisesMessage(CommandError, 'either an organisation slug or --all'):
            call_command('export_organization', 'alpha-org', '--all', '--out', self.out)
        self.assertEqual(list(Path(self.out).iterdir()), [])
        self.assertFalse(AuditEvent.objects.filter(action='organization.exported').exists())


class CrossOrganisationLinkTest(MediaRootMixin, TestCase):
    """A link that points outside the archive must not leak the other record's name.

    The admin's raw-id fields allow a Rock dependency or an Issue delegation to cross
    organisations; the JSON keeps only the pk, and the CSV must do the same.
    """

    def setUp(self):
        super().setUp()
        self.a = populate_org('Alpha')
        self.b = populate_org('Beta')
        RockDependency.objects.create(
            rock=self.a['rock'], depends_on_rock=self.b['rock'], description='crosses orgs',
        )
        self.a['issue'].delegated_to_team = self.b['team2']
        self.a['issue'].save()
        blob, _ = export_to_bytes(self.a['org'])
        self.archive = zipfile.ZipFile(io.BytesIO(blob))

    def rows(self, name):
        text = self.archive.read(f'csv/{name}.csv').decode()
        reader = csv.DictReader(io.StringIO(text))
        return list(reader)

    def test_rock_dependency_csv_keeps_the_id_but_not_the_other_rock_title(self):
        row = next(r for r in self.rows('rockdependency') if r['description'] == 'crosses orgs')
        self.assertEqual(row['depends_on_rock_id'], str(self.b['rock'].pk))
        self.assertEqual(row['depends_on_rock'], '')
        self.assertEqual(row['rock'], str(self.a['rock']))
        self.assertNotIn(self.b['rock'].title, self.archive.read('csv/rockdependency.csv').decode())

    def test_delegated_issue_csv_does_not_name_the_other_organisations_team(self):
        row = next(r for r in self.rows('issue') if r['id'] == str(self.a['issue'].pk))
        self.assertEqual(row['delegated_to_team_id'], str(self.b['team2'].pk))
        self.assertEqual(row['delegated_to_team'], '')
        self.assertNotIn(self.b['team2'].name, self.archive.read('csv/issue.csv').decode())

    def test_json_keeps_only_the_dangling_pk(self):
        import json
        records = json.loads(self.archive.read('data/rocks.rockdependency.json'))
        crossing = [r for r in records if r['fields']['description'] == 'crosses orgs']
        self.assertEqual(crossing[0]['fields']['depends_on_rock'], self.b['rock'].pk)
        self.assertNotIn(self.b['rock'].title, self.archive.read('data/rocks.rockdependency.json').decode())
