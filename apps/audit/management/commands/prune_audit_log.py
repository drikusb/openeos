from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.audit.models import AuditEvent


class Command(BaseCommand):
    help = (
        'Delete audit events older than --days (default 365). Intended to run from an '
        'external scheduler alongside send_daily_notifications.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=365,
            help='Delete events created more than this many days ago (default: 365).',
        )

    def handle(self, *args, **options):
        days = options['days']
        if days < 0:
            raise CommandError('--days must be zero or greater.')
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = AuditEvent.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(
            f'Deleted {deleted} audit event(s) older than {days} day(s).'
        ))
