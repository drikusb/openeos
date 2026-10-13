import json
from datetime import timezone as dt_timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import Organization
from apps.accounts.portability import FORMAT_VERSION, archive_filename, build_archive
from apps.audit.services import record


class Command(BaseCommand):
    help = (
        'Write one organisation (by slug) or every organisation (--all) to portable zip '
        'archives, one per organisation. Each export is recorded in the audit log.'
    )

    def add_arguments(self, parser):
        parser.add_argument('slug', nargs='?', help='Slug of the organisation to export.')
        parser.add_argument(
            '--all', action='store_true', dest='everything',
            help='Export every organisation and write instance-manifest.json listing them.',
        )
        parser.add_argument(
            '--out', default='.', metavar='DIR',
            help='Directory to write the archives into (default: the current directory).',
        )

    def handle(self, *args, **options):
        slug, everything = options['slug'], options['everything']
        if bool(slug) == everything:
            raise CommandError('Give either an organisation slug or --all, not both, not neither.')

        out_dir = Path(options['out'])
        out_dir.mkdir(parents=True, exist_ok=True)

        if everything:
            organizations = list(Organization.objects.order_by('slug'))
        else:
            try:
                organizations = [Organization.objects.get(slug=slug)]
            except Organization.DoesNotExist:
                raise CommandError(f'No organisation has the slug "{slug}".')

        entries = []
        for org in organizations:
            entries.append(self.export_one(org, out_dir))

        if everything:
            index = out_dir / 'instance-manifest.json'
            index.write_text(json.dumps({
                'format_version': FORMAT_VERSION,
                'exported_at': timezone.now().astimezone(dt_timezone.utc)
                .isoformat(timespec='seconds'),
                'archives': entries,
            }, indent=2), encoding='utf-8')
            self.stdout.write(str(index))
            self.stdout.write(self.style.SUCCESS(
                f'Exported {len(entries)} organisation(s) to {out_dir}.'
            ))

    def export_one(self, org, out_dir):
        now = timezone.now()
        path = out_dir / archive_filename(org, now)
        try:
            with open(path, 'wb') as fh:
                manifest = build_archive(org, fileobj=fh, via='command', exported_at=now)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        size = path.stat().st_size
        record(
            'organization.exported', organization=org, target=org, details={
                'format_version': FORMAT_VERSION, 'via': 'command', 'size_bytes': size,
                'record_counts': manifest['record_counts'],
            },
        )
        self.stdout.write(str(path))
        return {
            'slug': org.slug, 'name': org.name, 'file': path.name, 'size_bytes': size,
            'record_counts': manifest['record_counts'],
        }
