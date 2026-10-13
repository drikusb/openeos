"""Loading an export back in: the round trip, users, media, dry run and refusals."""
import io
import json
import shutil
import tempfile
import zipfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.accountability.models import AccountabilityNode
from apps.accounts.models import Organization
from apps.accounts.portability import collect
from apps.audit.models import AuditEvent
from apps.meetings.models import Headline
from apps.rocks.models import Rock, RockDependency
from apps.scorecards.models import Scorecard
from apps.todos.models import ToDo
from apps.vto.models import VTO

from .test_portability import EDITED_AT, MediaRootMixin, export_to_bytes, populate_org


def to_ms(when):
    """Django's JSON serializer keeps datetimes to the millisecond; compare at that grain."""
    return when.replace(microsecond=when.microsecond // 1000 * 1000)


def rewrite_zip(source, target, replacements):
    """Copy ``source`` to ``target`` with some entries replaced (bytes, or None to drop)."""
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, 'w') as dst:
        for item in src.infolist():
            if item.filename in replacements:
                if replacements[item.filename] is not None:
                    dst.writestr(item.filename, replacements[item.filename])
            else:
                dst.writestr(item, src.read(item.filename))


class ImportTestBase(MediaRootMixin, TestCase):
    """An exported Alpha Org whose member and former member no longer exist by name.

    Renaming the accounts after the export makes the archive refer to two
    usernames this database does not have, so an import must create them,
    while ``alphaadmin`` is still here to be reused.
    """

    def setUp(self):
        super().setUp()
        self.a = populate_org('Alpha')
        self.out = tempfile.mkdtemp(prefix='openeos-import-')
        self.addCleanup(shutil.rmtree, self.out, ignore_errors=True)
        self.archive = Path(self.out, 'alpha.zip')
        blob, self.manifest = export_to_bytes(self.a['org'], exported_by=self.a['admin'])
        self.archive.write_bytes(blob)
        for key in ('member', 'former'):
            user = self.a[key]
            user.username = f'{user.username}-old'
            user.save()

    def run_import(self, *args, archive=None):
        out = StringIO()
        call_command(
            'import_organization', str(archive or self.archive), '--slug', 'alpha-copy', *args,
            stdout=out,
        )
        return out.getvalue()

    def media_files(self):
        return sorted(str(p.relative_to(self.media_root)) for p in Path(self.media_root).rglob('*')
                      if p.is_file())


class RoundTripTest(ImportTestBase):
    def setUp(self):
        super().setUp()
        self.output = self.run_import()
        self.new_org = Organization.objects.get(slug='alpha-copy')
        self.admin = self.a['admin']

    def test_every_model_comes_back_with_the_same_counts(self):
        counts = {label: qs.count() for label, qs in collect(self.new_org).items()}
        self.assertEqual(counts, self.manifest['record_counts'])
        self.assertEqual(self.new_org.name, 'Alpha Org')
        self.assertEqual(self.new_org.created_at, to_ms(self.a['org'].created_at))
        self.assertNotEqual(self.new_org.pk, self.a['org'].pk)
        # The source organisation is untouched.
        self.assertEqual(self.a['org'].memberships.count(), 2)
        self.assertEqual(Rock.objects.filter(team__organization=self.a['org']).count(), 2)

    def test_rocks_point_at_the_new_organisation(self):
        rock = Rock.objects.get(team__organization=self.new_org, title='Alpha Rock')
        self.assertEqual(
            (rock.description, rock.status, rock.quarter, rock.year, str(rock.due_date)),
            ('Done looks like done', Rock.STATUS_OFF_TRACK, 1, 2026, '2026-03-31'),
        )
        self.assertEqual(rock.created_at, to_ms(self.a['rock'].created_at))
        self.assertEqual(rock.owner, self.admin)
        self.assertEqual(rock.created_by, self.admin)
        self.assertEqual(rock.team.name, 'Alpha Leadership')
        self.assertEqual(rock.milestones.get().title, 'Alpha Milestone')
        self.assertEqual(rock.checkins.get().note, 'Alpha slipping')

        child = Rock.objects.get(team__organization=self.new_org, title='Alpha Child Rock')
        self.assertEqual(child.parent_rock, rock)
        self.assertNotEqual(child.parent_rock_id, self.a['rock'].pk)
        self.assertEqual(child.team.organization, self.new_org)
        self.assertEqual(child.owner.username, 'alphamember')
        self.assertNotEqual(child.owner, self.a['member'])
        self.assertEqual(RockDependency.objects.get(rock=child).depends_on_rock, rock)

    def test_links_between_apps_follow_the_new_keys(self):
        rock = Rock.objects.get(team__organization=self.new_org, title='Alpha Rock')
        todo = ToDo.objects.get(team__organization=self.new_org)
        self.assertEqual(todo.linked_rock, rock)
        self.assertEqual(todo.linked_rock.team.organization, self.new_org)
        self.assertEqual(str(todo.due_date), '2026-02-01')
        issue = todo.linked_issue
        self.assertEqual(issue.title, 'Alpha Issue')
        self.assertEqual(issue.originating_team.organization, self.new_org)
        self.assertEqual(issue.delegated_to_team.name, 'Alpha Sales')
        self.assertEqual(issue.delegated_to_team.organization, self.new_org)
        self.assertEqual(list(issue.linked_rocks.all()), [rock])
        self.assertEqual(issue.created_by.username, 'alphaformer')
        self.assertEqual(issue.activity.get().actor, self.admin)

        headline = Headline.objects.get(meeting__team__organization=self.new_org)
        self.assertEqual(headline.escalated_issue, issue)
        self.assertEqual(headline.author.username, 'alphamember')
        meeting = headline.meeting
        self.assertEqual(meeting.started_at, EDITED_AT)
        self.assertEqual(meeting.cascading_messages, 'Alpha cascade')
        self.assertEqual(meeting.notes.get().text, 'Alpha IDS notes')
        self.assertEqual(meeting.segue_entries.get().participant, self.admin)
        self.assertEqual(meeting.ratings.get().score, 9)

    def test_chart_vto_and_scorecard(self):
        node = AccountabilityNode.objects.get(organization=self.new_org, name='Alpha Integrator')
        self.assertEqual(node.parent.name, 'Alpha Visionary')
        self.assertEqual(node.parent.organization, self.new_org)
        self.assertEqual(node.parent.owner, self.admin)
        self.assertEqual(node.roles.get().description, 'Alpha LMA')

        vto = self.new_org.vto
        self.assertEqual(vto.core_values.get().name, 'Alpha Value')
        section = vto.sections.get()
        self.assertEqual(section.content, 'Alpha target')
        self.assertEqual(section.last_edited_at, EDITED_AT)
        self.assertEqual(section.last_edited_by, self.admin)
        self.assertEqual(section.history.get().content, 'Alpha old target')

        metric = Scorecard.objects.get(team__organization=self.new_org).metrics.get()
        self.assertEqual(metric.goal_value, Decimal('10.5000'))
        self.assertEqual(metric.goal_direction, 'below')
        entry = metric.entries.get()
        self.assertEqual(entry.value, Decimal('7.2500'))
        self.assertTrue(entry.on_track)
        self.assertEqual(entry.entered_by.username, 'alphamember')

    def test_existing_user_is_reused_and_missing_users_are_created(self):
        admin = User.objects.get(username='alphaadmin')
        self.assertEqual(admin, self.admin)
        self.assertTrue(admin.check_password('pw'))
        self.assertEqual(
            set(admin.memberships.values_list('organization__slug', 'role')),
            {('alpha-org', 'admin'), ('alpha-copy', 'admin')},
        )
        self.assertEqual(
            set(admin.profile.teams.values_list('organization__slug', 'name')),
            {('alpha-org', 'Alpha Leadership'), ('alpha-org', 'Alpha Sales'),
             ('alpha-copy', 'Alpha Leadership'), ('alpha-copy', 'Alpha Sales')},
        )
        self.assertEqual(admin.profile.avatar.name, 'avatars/alpha-avatar.png')

        member = User.objects.get(username='alphamember')
        self.assertFalse(member.has_usable_password())
        self.assertEqual((member.first_name, member.last_name), ('Alpha', 'Member'))
        self.assertEqual(member.email, 'alphamember@example.com')
        self.assertEqual(member.date_joined, to_ms(self.a['member'].date_joined))
        self.assertFalse(member.is_staff)
        self.assertFalse(member.is_superuser)
        self.assertEqual(
            list(member.memberships.values_list('organization__slug', 'role')),
            [('alpha-copy', 'member')],
        )
        self.assertEqual(
            list(member.profile.teams.values_list('organization__slug', 'name')),
            [('alpha-copy', 'Alpha Leadership')],
        )
        self.assertFalse(member.notification_preference.meeting_reminders)

        former = User.objects.get(username='alphaformer')
        self.assertFalse(former.has_usable_password())
        self.assertEqual(former.memberships.count(), 0)
        self.assertEqual(User.objects.count(), 5)

    def test_media_is_restored_under_fresh_names(self):
        logo = self.new_org.logo.name
        self.assertTrue(logo.startswith('org_logos/alpha-logo'))
        self.assertNotEqual(logo, 'org_logos/alpha-logo.png')
        self.assertEqual(Path(self.media_root, logo).read_bytes(), b'Alpha logo bytes')
        self.assertEqual(
            Path(self.media_root, 'org_logos/alpha-logo.png').read_bytes(), b'Alpha logo bytes'
        )
        avatar = User.objects.get(username='alphamember').profile.avatar.name
        self.assertTrue(avatar.startswith('avatars/alpha-member-avatar'))
        self.assertNotEqual(avatar, 'avatars/alpha-member-avatar.png')
        self.assertEqual(Path(self.media_root, avatar).read_bytes(), b'Alpha member avatar')
        # The reused admin keeps their own avatar, so that file is not copied.
        self.assertEqual(len(self.media_files()), 5)

    def test_audit_row_and_summary(self):
        event = AuditEvent.objects.get(action='organization.imported')
        self.assertEqual(event.organization, self.new_org)
        self.assertIsNone(event.actor)
        self.assertEqual(event.target_type, 'accounts.organization')
        self.assertEqual(event.target_id, str(self.new_org.pk))
        self.assertEqual(event.details['format_version'], 1)
        self.assertEqual(event.details['source_organization'], 'Alpha Org')
        self.assertEqual(event.details['source_slug'], 'alpha-org')
        self.assertEqual(event.details['record_counts'], self.manifest['record_counts'])
        self.assertEqual(event.details['users_created'], ['alphamember', 'alphaformer'])
        self.assertEqual(event.details['users_reused'], ['alphaadmin'])

        self.assertIn('Imported "Alpha Org" (slug alpha-copy', self.output)
        self.assertIn('rocks.rock', self.output)
        self.assertIn('alphamember, alphaformer', self.output)
        self.assertIn('org_logos/alpha-logo.png -> org_logos/alpha-logo', self.output)
        self.assertNotIn('Dry run', self.output)


class ImportOptionsTest(ImportTestBase):
    def snapshot(self):
        return (
            Organization.objects.count(), User.objects.count(), Rock.objects.count(),
            AuditEvent.objects.count(), self.media_files(),
        )

    def test_dry_run_leaves_nothing_behind(self):
        before = self.snapshot()
        output = self.run_import('--dry-run')
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(Organization.objects.filter(slug='alpha-copy').exists())
        self.assertIn('Dry run: nothing was changed', output)
        self.assertIn('rocks.rock', output)
        self.assertIn('alphamember, alphaformer', output)
        self.assertIn('org_logos/alpha-logo.png -> org_logos/alpha-logo', output)

    def test_name_override(self):
        self.run_import('--name', 'Alpha Copy')
        org = Organization.objects.get(slug='alpha-copy')
        self.assertEqual(org.name, 'Alpha Copy')

    def test_refuses_an_existing_slug(self):
        with self.assertRaisesMessage(CommandError, 'slug "alpha-org" already exists'):
            call_command('import_organization', str(self.archive))
        self.assertEqual(Organization.objects.count(), 1)

    def test_refuses_an_unknown_format_version(self):
        manifest = dict(self.manifest, format_version=99)
        bad = Path(self.out, 'bad-version.zip')
        rewrite_zip(self.archive, bad, {'manifest.json': json.dumps(manifest).encode()})
        before = self.snapshot()
        with self.assertRaisesMessage(CommandError, 'format version 99'):
            self.run_import(archive=bad)
        self.assertEqual(self.snapshot(), before)

    def test_refuses_a_dangling_reference(self):
        with zipfile.ZipFile(self.archive) as src:
            todos = json.loads(src.read('data/todos.todo.json'))
        todos[0]['fields']['linked_rock'] = 999999
        bad = Path(self.out, 'dangling.zip')
        rewrite_zip(self.archive, bad, {'data/todos.todo.json': json.dumps(todos).encode()})
        before = self.snapshot()
        with self.assertRaisesMessage(
            CommandError, 'todos.todo.linked_rock refers to rocks.rock #999999'
        ):
            self.run_import(archive=bad)
        # Rolled back: no organisation, no users, and the logo copied before the
        # failure has been removed again.
        self.assertEqual(self.snapshot(), before)

    def test_refuses_something_that_is_not_an_export(self):
        with self.assertRaisesMessage(CommandError, 'is not a file'):
            self.run_import(archive=Path(self.out, 'missing.zip'))
        not_zip = Path(self.out, 'notes.txt')
        not_zip.write_text('hello')
        with self.assertRaisesMessage(CommandError, 'is not a zip archive'):
            self.run_import(archive=not_zip)
        empty = Path(self.out, 'empty.zip')
        with zipfile.ZipFile(empty, 'w') as z:
            z.writestr('hello.txt', 'hello')
        with self.assertRaisesMessage(CommandError, 'no manifest.json'):
            self.run_import(archive=empty)

    def test_media_missing_from_the_archive_is_left_blank(self):
        without_logo = Path(self.out, 'no-logo.zip')
        rewrite_zip(self.archive, without_logo, {'media/org_logos/alpha-logo.png': None})
        output = self.run_import(archive=without_logo)
        org = Organization.objects.get(slug='alpha-copy')
        self.assertEqual(org.logo.name, '')
        self.assertIn('not in the archive (left blank): org_logos/alpha-logo.png', output)


class ImportArchiveApiTest(ImportTestBase):
    def test_import_archive_accepts_a_file_object_and_an_actor(self):
        from apps.accounts.portability.importer import import_archive
        with io.BytesIO(self.archive.read_bytes()) as fh:
            result = import_archive(fh, slug='alpha-copy', actor=self.a['admin'])
        self.assertEqual(result.organization.slug, 'alpha-copy')
        self.assertEqual(result.record_counts, self.manifest['record_counts'])
        event = AuditEvent.objects.get(action='organization.imported')
        self.assertEqual(event.actor, self.a['admin'])
        self.assertEqual(result.skipped, [])
        self.assertEqual(event.details['skipped'], [])


class SkippedRowsTest(ImportTestBase):
    """A row that would break a unique constraint is skipped, with whatever depends on it."""

    def duplicate_vto_archive(self):
        """An archive with a second V/TO for the organisation and a core value on it.

        Organisation and V/TO are one-to-one, so the second V/TO already
        exists by the time it is met; the core value then refers to a row
        that was never created.
        """
        with zipfile.ZipFile(self.archive) as src:
            vtos = json.loads(src.read('data/vto.vto.json'))
            values = json.loads(src.read('data/vto.vtocorevalue.json'))
        duplicate = dict(vtos[0], pk=999999)
        orphan = dict(values[0], pk=999998)
        orphan['fields'] = dict(values[0]['fields'], vto=999999, name='Alpha orphan value')
        bad = Path(self.out, 'duplicate-vto.zip')
        rewrite_zip(self.archive, bad, {
            'data/vto.vto.json': json.dumps(vtos + [duplicate]).encode(),
            'data/vto.vtocorevalue.json': json.dumps(values + [orphan]).encode(),
        })
        return bad

    def test_unique_violation_skips_the_row_and_what_depends_on_it(self):
        output = self.run_import(archive=self.duplicate_vto_archive())
        org = Organization.objects.get(slug='alpha-copy')
        self.assertEqual(VTO.objects.filter(organization=org).count(), 1)
        self.assertEqual(
            list(org.vto.core_values.values_list('name', flat=True)), ['Alpha Value']
        )
        self.assertIn('Skipped 2 record(s)', output)
        self.assertIn('vto.vto #999999: Vto with this Organization already exists.', output)
        self.assertIn(
            'vto.vtocorevalue #999998: its vto (vto.vto #999999) was skipped', output
        )

        event = AuditEvent.objects.get(action='organization.imported')
        self.assertEqual(event.details['record_counts']['vto.vto'], 1)
        self.assertEqual(event.details['record_counts']['vto.vtocorevalue'], 1)
        self.assertEqual(event.details['skipped'], [
            {'model': 'vto.vto', 'pk': 999999,
             'reason': 'Vto with this Organization already exists.'},
            {'model': 'vto.vtocorevalue', 'pk': 999998,
             'reason': 'its vto (vto.vto #999999) was skipped'},
        ])

    def test_dry_run_reports_what_would_be_skipped(self):
        output = self.run_import('--dry-run', archive=self.duplicate_vto_archive())
        self.assertIn('Dry run', output)
        self.assertIn('vto.vto #999999: Vto with this Organization already exists.', output)
        self.assertFalse(Organization.objects.filter(slug='alpha-copy').exists())
