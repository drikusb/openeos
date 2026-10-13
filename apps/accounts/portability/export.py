"""Write everything that belongs to one organisation into a zip archive.

:func:`collect` is the single statement of what belongs to an organisation,
in dependency order (parents before children); the web view, the management
command and the importer all go through it. :func:`build_archive` turns that
into the archive described in README.txt inside every export.

What belongs to an organisation is discovered from the model registry rather
than listed by hand, so a model added to one of the EOS apps is exported as
soon as it exists. A model is organisation-scoped when it has a ForeignKey or
OneToOneField to ``accounts.Organization`` or to another organisation-scoped
model; :func:`organization_lookup` gives the ORM path that scopes it. The
two models that reach the organisation only through their user (the profile
and the notification preferences) are collected for the exported users, and
``auth.User`` itself is the members plus anyone a record still refers to.
"""
import csv
import heapq
import io
import json
import zipfile
from collections import OrderedDict
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

import django
from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import User
from django.core import serializers
from django.core.files.storage import default_storage
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q
from django.db.models.fields.files import FieldFile
from django.utils import timezone

from apps.accounts.models import Membership, Organization, UserProfile

FORMAT_VERSION = 1

# The apps whose models make up an organisation's data. apps.audit is left
# out on purpose: the audit log is the instance's history, not the
# organisation's data, and it refers to records by id rather than owning them.
PORTABLE_APPS = (
    'accountability', 'accounts', 'issues', 'meetings', 'notifications', 'rocks',
    'scorecards', 'todos', 'vto',
)

# Models of the portable apps that are deliberately not exported, as
# ``app_label.model_name``. Empty today; the test against the app registry
# fails for any model that is neither collected nor listed here.
EXCLUDED_MODELS = frozenset()

# Models that belong to a user rather than to an organisation. They are
# exported for the users the archive carries, not by a path to the
# organisation (they have none).
USER_OWNED_MODELS = frozenset({'accounts.userprofile', 'notifications.notificationpreference'})

# The only columns of auth.User that leave the instance. No password hash, no
# staff or superuser flags, no groups or permissions: those belong to the
# instance the account lives on, not to the organisation.
USER_FIELDS = (
    'username', 'first_name', 'last_name', 'email', 'is_active', 'date_joined', 'last_login',
)

USER_LABEL = 'auth.user'

# A file whose first line names the running build (written by the deployment).
BUILD_INFO_PATH = settings.BASE_DIR / 'BUILD_INFO'


class ArchiveTooLarge(Exception):
    """Raised by :func:`build_archive` when the archive would exceed ``max_bytes``."""

    def __init__(self, max_bytes):
        super().__init__(f'The archive would exceed {max_bytes} bytes.')
        self.max_bytes = max_bytes


def label_for(model):
    return f'{model._meta.app_label}.{model._meta.model_name}'


def collect(organization):
    """Return ``OrderedDict[model_label, queryset]`` of everything in the organisation.

    Keys are ``app_label.model_name`` in dependency order, so a reader that
    loads the files in this order always meets a parent before its children.
    The user set is every member plus any account a record still refers to
    (a former member who owns a Rock, say), so the archive is self-contained.
    """
    org = organization
    paths = _organization_paths()
    scoped = {
        model: model._default_manager.filter(_organization_filter(model, org, paths))
        for model in _scoped_models(paths)
    }
    user_pks = set(
        Membership._default_manager.filter(organization=org).values_list('user_id', flat=True)
    )
    user_pks.update(_referenced_user_pks(scoped.values()))
    users = User._default_manager.filter(pk__in=user_pks)

    collected = OrderedDict()
    for model in portable_models():
        if model is User:
            queryset = users
        elif model in scoped:
            queryset = scoped[model]
        else:
            queryset = model._default_manager.filter(**{_user_field(model).name + '__in': users})
        collected[label_for(model)] = queryset.order_by('pk')
    return collected


def portable_models():
    """Every model the archive carries, in the order the files are written.

    That is ``auth.User`` plus every model of the portable apps that is
    organisation-scoped or user-owned, sorted so that a model comes after
    everything its foreign keys and many-to-many fields point at. Ties are
    broken by ``app_label.model_name`` so the layout is the same on every
    instance. Self-references (a parent Rock, a parent chart seat) are not
    dependencies; the importer orders those rows itself.
    """
    chosen = [User] + _scoped_models(_organization_paths()) + [
        model for model in _candidate_models() if label_for(model) in USER_OWNED_MODELS
    ]
    depends_on = {model: set() for model in chosen}
    for model in chosen:
        for field in _relation_fields(model, many=True):
            if field.related_model in depends_on and field.related_model is not model:
                depends_on[model].add(field.related_model)
    waiting = {model: len(deps) for model, deps in depends_on.items()}
    ready = [(label_for(m), m) for m, n in waiting.items() if n == 0]
    heapq.heapify(ready)
    ordered = []
    while ready:
        _, model = heapq.heappop(ready)
        ordered.append(model)
        for child, deps in depends_on.items():
            if model in deps:
                waiting[child] -= 1
                if waiting[child] == 0:
                    heapq.heappush(ready, (label_for(child), child))
    if len(ordered) != len(chosen):
        stuck = sorted(label_for(m) for m, n in waiting.items() if n > 0)
        raise ValueError(f'These models refer to each other in a loop: {", ".join(stuck)}.')
    return ordered


def organization_lookup(model):
    """The ORM path from ``model`` to its organisation (``team__organization``), or None.

    The organisation itself has the empty path. Among several paths the one
    that crosses no nullable foreign key wins, then the shortest, then the
    one through the field declared first on the model, so a direct
    ``organization`` field beats a route through a team, a required team
    beats an optional one, and a Rock dependency is scoped by the Rock that
    owns it rather than the Rock it depends on.
    """
    best = _organization_paths().get(model)
    return best[0] if best else None


def _organization_paths():
    """``{model: (path, hops, nullable, field index)}`` per organisation-scoped model.

    Starts from the organisation and keeps relaxing until nothing improves,
    so cycles between models and self-references cannot loop for ever.
    """
    best = {Organization: ('', 0, False, 0)}
    candidates = [m for m in _candidate_models() if m is not Organization]
    changed = True
    while changed:
        changed = False
        for model in candidates:
            for index, field in enumerate(_relation_fields(model)):
                target = field.related_model
                if target is model or target not in best:
                    continue
                target_path, hops, nullable, _ = best[target]
                path = f'{field.name}__{target_path}' if target_path else field.name
                found = (path, hops + 1, nullable or bool(field.null), index)
                if model not in best or _path_rank(found) < _path_rank(best[model]):
                    best[model] = found
                    changed = True
    return best


def _path_rank(entry):
    _, hops, nullable, index = entry
    return (nullable, hops, index)


def _organization_filter(model, org, paths):
    """A ``Q`` that keeps ``model``'s rows belonging to ``org``.

    When the best path crosses an optional foreign key a row may reach the
    organisation another way instead, so every path is tried, not just the
    best one.
    """
    if model is Organization:
        return Q(pk=org.pk)
    path, _, nullable, _ = paths[model]
    if not nullable:
        return Q(**{path: org})
    query = Q()
    for field in _relation_fields(model):
        target = field.related_model
        if target is model or target not in paths:
            continue
        target_path = paths[target][0]
        query |= Q(**{f'{field.name}__{target_path}' if target_path else field.name: org})
    return query


def _scoped_models(paths):
    """The organisation-scoped models, the organisation first, then by label."""
    scoped = [m for m in _candidate_models() if m in paths]
    return sorted(scoped, key=lambda m: (m is not Organization, label_for(m)))


def _candidate_models():
    """Every concrete model of the portable apps that is not excluded."""
    found = []
    for app_label in PORTABLE_APPS:
        for model in apps.get_app_config(app_label).get_models():
            opts = model._meta
            if opts.proxy or opts.auto_created or label_for(model) in EXCLUDED_MODELS:
                continue
            found.append(model)
    return found


def _relation_fields(model, many=False):
    fields = [f for f in model._meta.concrete_fields if f.is_relation]
    if many:
        fields += list(model._meta.many_to_many)
    return fields


def _user_field(model):
    for field in _relation_fields(model):
        if field.related_model is User:
            return field
    raise LookupError(f'{label_for(model)} has no field pointing at auth.User.')


def _referenced_user_pks(querysets):
    pks = set()
    for queryset in querysets:
        for field in queryset.model._meta.concrete_fields:
            if isinstance(field, models.ForeignKey) and field.related_model is User:
                pks.update(
                    queryset.exclude(**{f'{field.name}__isnull': True})
                    .values_list(field.attname, flat=True)
                )
    return pks


def archive_filename(organization, when):
    stamp = when.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%MZ')
    return f'openeos-export-{organization.slug}-{stamp}.zip'


def build_archive(organization, *, fileobj, exported_by=None, via='web', max_bytes=None,
                  exported_at=None):
    """Write the organisation's archive to ``fileobj`` and return the manifest.

    ``fileobj`` must be a seekable binary file open for writing. With
    ``max_bytes`` set, :class:`ArchiveTooLarge` is raised before any entry
    that would take the archive past the limit.
    """
    exported_at = exported_at or timezone.now()
    collected = collect(organization)
    exported_pks = {
        label: set(queryset.values_list('pk', flat=True))
        for label, queryset in collected.items()
    }
    record_counts = OrderedDict()
    media = []

    archive = zipfile.ZipFile(fileobj, 'w', zipfile.ZIP_DEFLATED)
    try:
        for label, queryset in collected.items():
            records = _records(label, queryset, exported_pks)
            record_counts[label] = len(records)
            _put(archive, f'data/{label}.json', _json(records), max_bytes)
            _put(archive, f'csv/{queryset.model._meta.model_name}.csv',
                 _csv(label, queryset, exported_pks), max_bytes)
        for name, content in _media_files(organization, collected[USER_LABEL]):
            _put(archive, f'media/{name}', content, max_bytes)
            media.append(name)
        manifest = OrderedDict([
            ('format_version', FORMAT_VERSION),
            ('exported_at', exported_at.astimezone(dt_timezone.utc).isoformat(timespec='seconds')),
            ('exported_by', exported_by.get_username() if exported_by else None),
            ('via', via),
            ('organization', {
                'id': organization.pk, 'name': organization.name, 'slug': organization.slug,
            }),
            ('app', {'django': django.get_version(), 'openeos_build': _build_id()}),
            ('record_counts', record_counts),
            ('files', media),
        ])
        _put(archive, 'manifest.json', _json(manifest), max_bytes)
        _put(archive, 'README.txt', _readme(manifest), max_bytes)
    finally:
        archive.close()
    return manifest


def _put(archive, name, payload, max_bytes):
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    if max_bytes is not None and archive.fp.tell() + len(payload) > max_bytes:
        raise ArchiveTooLarge(max_bytes)
    archive.writestr(name, payload)


def _json(value):
    return json.dumps(value, cls=DjangoJSONEncoder, indent=2, ensure_ascii=False)


def _build_id(path=None):
    """The first line of the build-info file, or None when there is no such file."""
    path = path or BUILD_INFO_PATH
    try:
        text = path.read_text(encoding='utf-8').strip()
    except OSError:
        return None
    return text.splitlines()[0].strip() if text else None


# ── data/<label>.json ──────────────────────────────────────────────────────

def _records(label, queryset, exported_pks):
    """The model's rows in the shape of Django's JSON serializer, with plain pks."""
    if label == USER_LABEL:
        return [
            {'model': USER_LABEL, 'pk': user.pk,
             'fields': {name: getattr(user, name) for name in USER_FIELDS}}
            for user in queryset
        ]
    # The 'python' serializer is the JSON serializer before encoding: same
    # shape, and the lists are still editable here.
    records = serializers.serialize('python', queryset, use_natural_foreign_keys=False)
    many_to_many = [
        (field.name, label_for(field.related_model))
        for field in queryset.model._meta.many_to_many
    ]
    for record in records:
        for name, target in many_to_many:
            # A profile may sit on teams of other organisations; an archive
            # only refers to what it carries.
            if target in exported_pks:
                record['fields'][name] = [
                    pk for pk in record['fields'][name] if pk in exported_pks[target]
                ]
    return records


# ── csv/<model_name>.csv ───────────────────────────────────────────────────

def _csv(label, queryset, exported_pks):
    out = io.StringIO()
    writer = csv.writer(out)
    if label == USER_LABEL:
        writer.writerow(('id',) + USER_FIELDS)
        for user in queryset:
            writer.writerow([_cell(user.pk)] + [_cell(getattr(user, f)) for f in USER_FIELDS])
        return out.getvalue()

    opts = queryset.model._meta
    plain = [f for f in opts.concrete_fields if not f.is_relation]
    foreign = [f for f in opts.concrete_fields if f.is_relation]
    many = list(opts.many_to_many)
    header = [f.name for f in plain]
    for field in foreign:
        header += [field.name, f'{field.name}_id']
    for field in many:
        header += [field.name, f'{field.name}_ids']
    writer.writerow(header)

    queryset = queryset.select_related(*_related_paths(foreign))
    if many:
        queryset = queryset.prefetch_related(*[f.name for f in many])
    for obj in queryset:
        row = [_cell(getattr(obj, f.attname)) for f in plain]
        for field in foreign:
            related = getattr(obj, field.name)
            row += [_cell(related), _cell(getattr(obj, field.attname))]
        for field in many:
            related = getattr(obj, field.name).all()
            carried = exported_pks.get(label_for(field.related_model))
            if carried is not None:
                related = [r for r in related if r.pk in carried]
            row += ['; '.join(str(r) for r in related), '; '.join(str(r.pk) for r in related)]
        writer.writerow(row)
    return out.getvalue()


def _related_paths(foreign):
    """Follow each FK one hop further so ``str()`` of the related row is a free lookup."""
    paths = []
    for field in foreign:
        paths.append(field.name)
        for nested in field.related_model._meta.concrete_fields:
            if nested.is_relation and nested.related_model is not User:
                paths.append(f'{field.name}__{nested.name}')
    return paths


def _cell(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, FieldFile):
        return value.name or ''
    if isinstance(value, models.Model):
        return str(value)
    return value


# ── media/ ─────────────────────────────────────────────────────────────────

def _media_files(organization, users):
    names = []
    if organization.logo:
        names.append(organization.logo.name)
    avatars = (
        UserProfile.objects.filter(user__in=users)
        .exclude(avatar='').exclude(avatar__isnull=True)
        .values_list('avatar', flat=True)
    )
    names.extend(avatars)
    for name in names:
        if not default_storage.exists(name):
            continue
        with default_storage.open(name, 'rb') as fh:
            yield name, fh.read()


# ── README.txt ─────────────────────────────────────────────────────────────

def _readme(manifest):
    org = manifest['organization']
    counts = '\n'.join(
        f'  {label:<42} {count:>7}' for label, count in manifest['record_counts'].items()
    )
    files = '\n'.join(f'  media/{name}' for name in manifest['files']) or '  (none)'
    return f"""OpenEOS organisation export
===========================

Organisation : {org['name']} (slug: {org['slug']}, id {org['id']})
Exported at  : {manifest['exported_at']}
Exported by  : {manifest['exported_by'] or '(management command)'}
Format       : {manifest['format_version']}
Django       : {manifest['app']['django']}
Build        : {manifest['app']['openeos_build'] or '(unknown)'}

What this archive contains
--------------------------
Everything that belongs to the organisation: the organisation record, its
teams, the memberships, the member accounts (name, email, username and
activity dates only; no password hashes or permissions), user profiles and
notification preferences, and every V/TO, Accountability Chart, Rock, Issue,
To-Do, Scorecard and Level 10 Meeting record, with the organisation logo and
members' avatars where the files exist.

Layout
------
  manifest.json          what was exported, when, by whom, and record counts
  README.txt             this file
  data/<app>.<model>.json
                         one file per model in Django serializer format
                         (plain primary keys, timestamps to the millisecond),
                         in dependency order: the organisation first, then
                         teams and users, then everything that points at them
  csv/<model>.csv        the same rows for spreadsheets; foreign keys appear
                         twice, as the related record's name and as its id
  media/<path>           uploaded files, at the path the records refer to

Record counts
-------------
{counts}

Files
-----
{files}

Importing
---------
On another OpenEOS instance run:

  python manage.py import_organization <this archive>

Add --slug to give the imported organisation a different slug and --dry-run
to see what would be created without changing anything. Members are matched
by username: an existing account is reused and given a membership, a missing
one is created without a usable password so its owner sets one through
"Forgot password?".
"""
