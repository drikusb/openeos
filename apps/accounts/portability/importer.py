"""Load an organisation archive written by :mod:`.export` into this instance.

Every record is created afresh with a new primary key; the old keys are
remembered per model so foreign keys and many-to-many lists can be rewritten
as they are met. Files are loaded in the order the archive lists them, which
is the dependency order :func:`.export.collect` wrote them in, so a parent
always exists before its children. A reference to anything the archive does
not carry is an error, not a null.

A row that would break a unique constraint this database already satisfies
(a hostname taken by another organisation, say) is skipped rather than
stopping the import, along with any row that refers to it; the result lists
every skipped row with the reason. The organisation itself is never skipped:
its slug is checked before anything is written.
"""
import json
import zipfile
from collections import OrderedDict

from django.apps import apps
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import models, transaction

from apps.accounts.models import Organization, UserProfile
from apps.audit.services import record
from apps.notifications.models import NotificationPreference

from .export import FORMAT_VERSION, USER_FIELDS, USER_LABEL, label_for

ORGANIZATION_LABEL = 'accounts.organization'
PROFILE_LABEL = 'accounts.userprofile'
PREFERENCE_LABEL = 'notifications.notificationpreference'


class PortabilityError(Exception):
    """The archive cannot be loaded as it is; the message says why."""


class ImportResult:
    """What an import did (or, for a dry run, would have done)."""

    def __init__(self, manifest, dry_run):
        self.manifest = manifest
        self.dry_run = dry_run
        self.organization = None
        self.record_counts = OrderedDict()
        self.users_created = []
        self.users_reused = []
        self.media_restored = []   # (name in the archive, name in MEDIA_ROOT)
        self.media_missing = []    # referred to by a record but not in the archive
        self.skipped = []          # (label, pk in the archive, reason) for rows not created

    @property
    def source_name(self):
        return self.manifest['organization']['name']


def import_archive(path, *, slug=None, name=None, dry_run=False, actor=None):
    """Load the archive at ``path`` and return an :class:`ImportResult`.

    ``slug`` and ``name`` replace the organisation's own. With ``dry_run``
    everything happens inside a transaction that is then rolled back, and no
    file is written to MEDIA_ROOT.
    """
    with zipfile.ZipFile(path) as archive:
        manifest = _read_manifest(archive)
        target_slug = slug or manifest['organization']['slug']
        target_name = name or manifest['organization']['name']
        if Organization.objects.filter(slug=target_slug).exists():
            raise PortabilityError(
                f'An organisation with the slug "{target_slug}" already exists here; '
                f'pass --slug to import under a different one.'
            )
        loader = _Loader(archive, manifest, dry_run=dry_run)
        try:
            with transaction.atomic():
                result = loader.load(target_slug, target_name, actor)
                if dry_run:
                    transaction.set_rollback(True)
        except Exception:
            loader.discard_written_media()
            raise
        return result


def _read_manifest(archive):
    try:
        manifest = json.loads(archive.read('manifest.json'))
    except KeyError:
        raise PortabilityError('This is not an OpenEOS export: it has no manifest.json.')
    version = manifest.get('format_version')
    if version != FORMAT_VERSION:
        raise PortabilityError(
            f'This archive is format version {version!r}; this version of OpenEOS reads '
            f'version {FORMAT_VERSION}.'
        )
    for key in ('organization', 'record_counts'):
        if key not in manifest:
            raise PortabilityError(f'manifest.json has no "{key}" entry.')
    return manifest


class _Loader:
    def __init__(self, archive, manifest, *, dry_run):
        self.archive = archive
        self.manifest = manifest
        self.dry_run = dry_run
        self.result = ImportResult(manifest, dry_run)
        self.maps = {}          # label -> {old pk: new pk}
        self.old_pks = {}       # label -> {old pk} as listed in the archive
        self.skipped = {}       # label -> {old pk: reason} for rows that were not created
        self.media_map = {}     # name in archive -> name in MEDIA_ROOT
        self.written_media = []
        self.new_user_pks = set()
        self.entries = set(archive.namelist())

    # ── driver ─────────────────────────────────────────────────────────────

    def load(self, slug, name, actor):
        labels = list(self.manifest['record_counts'])
        records = {label: self._records(label) for label in labels}
        self.old_pks = {label: {r['pk'] for r in rows} for label, rows in records.items()}
        for label in labels:
            self.maps.setdefault(label, {})
            rows = records[label]
            if label == ORGANIZATION_LABEL:
                self._load_organization(rows, slug, name)
            elif label == USER_LABEL:
                self._load_users(rows)
            elif label == PROFILE_LABEL:
                self._load_profiles(rows)
            elif label == PREFERENCE_LABEL:
                self._load_preferences(rows)
            else:
                self._load_model(label, rows)
            self.result.record_counts[label] = len(rows) - len(self.skipped.get(label, {}))

        org = self.result.organization
        record(
            'organization.imported', actor=actor, organization=org, target=org, details={
                'format_version': self.manifest['format_version'],
                'source_organization': self.result.source_name,
                'source_slug': self.manifest['organization']['slug'],
                'exported_at': self.manifest.get('exported_at'),
                'record_counts': dict(self.result.record_counts),
                'users_created': list(self.result.users_created),
                'users_reused': list(self.result.users_reused),
                'skipped': [
                    {'model': label, 'pk': pk, 'reason': reason}
                    for label, pk, reason in self.result.skipped
                ],
            },
        )
        return self.result

    def _records(self, label):
        entry = f'data/{label}.json'
        if entry not in self.entries:
            raise PortabilityError(f'The archive lists {label} but has no {entry}.')
        try:
            model = apps.get_model(label)
        except LookupError:
            raise PortabilityError(f'This instance has no model called {label}.')
        rows = json.loads(self.archive.read(entry))
        for row in rows:
            if row.get('model') != label or 'pk' not in row or 'fields' not in row:
                raise PortabilityError(f'{entry} holds a record that is not a {label}.')
        self._check_model_has_fields(model, label, rows)
        return rows

    @staticmethod
    def _check_model_has_fields(model, label, rows):
        known = {f.name for f in model._meta.get_fields()}
        for row in rows:
            unknown = set(row['fields']) - known
            if unknown:
                raise PortabilityError(
                    f'{label} has no field called {sorted(unknown)[0]}; the archive comes '
                    f'from a different version of OpenEOS.'
                )

    # ── the organisation, users, and the two one-to-one models ────────────

    def _load_organization(self, rows, slug, name):
        if len(rows) != 1:
            raise PortabilityError('The archive must hold exactly one organisation.')
        row = rows[0]
        fields = dict(row['fields'], slug=slug, name=name)
        org = self._create(Organization, ORGANIZATION_LABEL, dict(row, fields=fields))
        self.result.organization = org

    def _load_users(self, rows):
        for row in rows:
            fields = row['fields']
            username = fields.get('username')
            if not username:
                raise PortabilityError(f'auth.user #{row["pk"]} has no username.')
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User(**{
                    name: User._meta.get_field(name).to_python(fields.get(name))
                    for name in USER_FIELDS if name in fields
                })
                user.set_unusable_password()
                user.save()
                self.new_user_pks.add(user.pk)
                self.result.users_created.append(username)
            else:
                self.result.users_reused.append(username)
            self.maps[USER_LABEL][row['pk']] = user.pk

    def _load_profiles(self, rows):
        """A profile exists for every user already; fill in the new users', add teams."""
        for row in rows:
            user_pk = self._map(USER_LABEL, row['fields'].get('user'), f'{PROFILE_LABEL}.user')
            profile, _ = UserProfile.objects.get_or_create(user_id=user_pk)
            if user_pk in self.new_user_pks:
                self._apply_fields(profile, PROFILE_LABEL, row['fields'], skip={'user', 'teams'})
                profile.save_base(raw=True)
            teams = [
                self._map('accounts.team', pk, f'{PROFILE_LABEL}.teams')
                for pk in row['fields'].get('teams', [])
            ]
            profile.teams.add(*teams)
            self.maps[PROFILE_LABEL][row['pk']] = profile.pk

    def _load_preferences(self, rows):
        for row in rows:
            user_pk = self._map(USER_LABEL, row['fields'].get('user'), f'{PREFERENCE_LABEL}.user')
            pref, _ = NotificationPreference.objects.get_or_create(user_id=user_pk)
            if user_pk in self.new_user_pks:
                self._apply_fields(pref, PREFERENCE_LABEL, row['fields'], skip={'user'})
                pref.save_base(raw=True)
            self.maps[PREFERENCE_LABEL][row['pk']] = pref.pk

    # ── everything else ───────────────────────────────────────────────────

    def _load_model(self, label, rows):
        model = apps.get_model(label)
        self_links = [
            f.name for f in model._meta.concrete_fields
            if f.is_relation and f.related_model is model
        ]
        pending = list(rows)
        while pending:
            waiting = []
            for row in pending:
                if self._waits_on_sibling(label, row, self_links):
                    waiting.append(row)
                else:
                    self._create(model, label, row)
            if len(waiting) == len(pending):
                raise PortabilityError(
                    f'{label} #{waiting[0]["pk"]} refers to itself in a loop and cannot be loaded.'
                )
            pending = waiting

    def _waits_on_sibling(self, label, row, self_links):
        for name in self_links:
            old = row['fields'].get(name)
            if old is None or old in self.maps[label] or old in self.skipped.get(label, {}):
                continue
            if old not in self.old_pks[label]:
                raise PortabilityError(
                    f'{label} #{row["pk"]} refers to {label} #{old}, which is not in the archive.'
                )
            return True
        return False

    def _create(self, model, label, row):
        """Insert one record with remapped keys, keeping its timestamps as exported.

        Returns None instead when the row is skipped: it refers to a row
        that was skipped, or it would break a unique constraint.
        """
        fields = row['fields']
        reason = self._skipped_parent(model, fields)
        if reason:
            return self._skip(label, row, reason)
        many = {}
        for field in model._meta.many_to_many:
            if field.name in fields:
                target = label_for(field.related_model)
                many[field.name] = [
                    self._map(target, pk, f'{label}.{field.name}')
                    for pk in fields[field.name] if pk not in self.skipped.get(target, {})
                ]
        obj = model()
        self._apply_fields(obj, label, fields, skip=set(many))
        if label != ORGANIZATION_LABEL:
            reason = self._unique_violation(obj)
            if reason:
                return self._skip(label, row, reason)
        obj.save_base(raw=True, force_insert=True)
        for name, pks in many.items():
            getattr(obj, name).set(pks)
        self.maps[label][row['pk']] = obj.pk
        return obj

    def _skipped_parent(self, model, fields):
        """Why this row cannot be created because of a skipped row it points at, or None."""
        for field in model._meta.concrete_fields:
            old = fields.get(field.name) if field.is_relation else None
            if old is None:
                continue
            target = label_for(field.related_model)
            if old in self.skipped.get(target, {}):
                return f'its {field.name} ({target} #{old}) was skipped'
        return None

    @staticmethod
    def _unique_violation(obj):
        """Why saving ``obj`` would break a unique constraint, or None when it would not."""
        try:
            obj.validate_unique()
            obj.validate_constraints()
        except ValidationError as exc:
            return ' '.join(m for messages in exc.message_dict.values() for m in messages)
        return None

    def _skip(self, label, row, reason):
        self.skipped.setdefault(label, {})[row['pk']] = reason
        self.result.skipped.append((label, row['pk'], reason))
        return None

    def _apply_fields(self, obj, label, fields, skip):
        for field in obj._meta.concrete_fields:
            if field.primary_key or field.name in skip or field.name not in fields:
                continue
            value = fields[field.name]
            if field.is_relation:
                if value is not None:
                    value = self._map(label_for(field.related_model), value,
                                      f'{label}.{field.name}')
                setattr(obj, field.attname, value)
            elif isinstance(field, models.FileField):
                setattr(obj, field.name, self._restore_media(value) if value else value)
            else:
                setattr(obj, field.name, field.to_python(value))

    def _map(self, target_label, old_pk, where):
        try:
            return self.maps[target_label][old_pk]
        except KeyError:
            raise PortabilityError(
                f'{where} refers to {target_label} #{old_pk}, which is not in the archive.'
            )

    # ── media ─────────────────────────────────────────────────────────────

    def _restore_media(self, name):
        """Copy ``media/<name>`` into MEDIA_ROOT and return the name it was stored under."""
        if name in self.media_map:
            return self.media_map[name]
        entry = f'media/{name}'
        if entry not in self.entries:
            self.result.media_missing.append(name)
            self.media_map[name] = ''
            return ''
        if self.dry_run:
            stored = default_storage.get_available_name(name)
        else:
            stored = default_storage.save(name, ContentFile(self.archive.read(entry)))
            self.written_media.append(stored)
        self.media_map[name] = stored
        self.result.media_restored.append((name, stored))
        return stored

    def discard_written_media(self):
        """After a failed import, remove the files the rolled-back records pointed at."""
        for stored in self.written_media:
            try:
                default_storage.delete(stored)
            except OSError:
                pass
        self.written_media = []
