import zipfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.portability.importer import PortabilityError, import_archive


class Command(BaseCommand):
    help = (
        'Load an organisation archive written by export_organization into this instance, '
        'as a new organisation with new primary keys. Members are matched by username.'
    )

    def add_arguments(self, parser):
        parser.add_argument('archive', help='Path to the zip archive.')
        parser.add_argument(
            '--slug', help='Slug for the imported organisation (default: the one in the archive).',
        )
        parser.add_argument(
            '--name', help='Name for the imported organisation (default: the one in the archive).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Load everything inside a transaction, report, then roll it back; no file is '
                 'written to MEDIA_ROOT.',
        )

    def handle(self, *args, **options):
        path = Path(options['archive'])
        if not path.is_file():
            raise CommandError(f'{path} is not a file.')
        try:
            result = import_archive(
                path, slug=options['slug'], name=options['name'], dry_run=options['dry_run'],
            )
        except zipfile.BadZipFile:
            raise CommandError(f'{path} is not a zip archive.')
        except PortabilityError as exc:
            raise CommandError(str(exc))
        self.report(result)

    def report(self, result):
        org = result.organization
        manifest = result.manifest
        write = self.stdout.write
        if result.dry_run:
            write(self.style.WARNING('Dry run: nothing was changed. The import would create:'))
        else:
            write(self.style.SUCCESS(f'Imported "{org.name}" (slug {org.slug}, id {org.pk}).'))
        write(f'  Source: "{result.source_name}" (slug {manifest["organization"]["slug"]}), '
              f'exported {manifest.get("exported_at")} by '
              f'{manifest.get("exported_by") or "the management command"}.')
        write('  Records:')
        for label, count in result.record_counts.items():
            write(f'    {label:<40} {count:>7}')
        created = ', '.join(result.users_created) or '(none)'
        reused = ', '.join(result.users_reused) or '(none)'
        write(f'  Users created without a usable password (they set one via "Forgot password?"): '
              f'{created}')
        write(f'  Existing accounts reused: {reused}')
        if result.media_restored:
            write('  Media restored:')
            for name, stored in result.media_restored:
                write(f'    {name} -> {stored}')
        if result.media_missing:
            write(self.style.WARNING(
                '  Files referred to by records but not in the archive (left blank): '
                + ', '.join(result.media_missing)
            ))
        if result.skipped:
            write(self.style.WARNING(
                f'  Skipped {len(result.skipped)} record(s) that would clash with what is '
                f'already here (or depend on one that would):'
            ))
            for label, pk, reason in result.skipped:
                write(f'    {label} #{pk}: {reason}')
