from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """One thing that happened, recorded for later review.

    Rows are written through :func:`apps.audit.services.record` and never edited.
    ``actor_label`` snapshots the username so the row stays readable after the
    user is deleted; ``organization`` and ``actor`` are nulled rather than
    cascading for the same reason.
    """

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_events',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_events',
    )
    actor_label = models.CharField(max_length=150, blank=True)
    action = models.CharField(
        max_length=100, db_index=True,
        help_text='Dotted lower-case name, e.g. user.login or organization.exported.',
    )
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    target_label = models.CharField(max_length=255, blank=True)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Audit event'
        verbose_name_plural = 'Audit events'
        indexes = [
            models.Index(fields=['organization', 'created_at'], name='audit_org_created_idx'),
        ]

    def __str__(self):
        who = self.actor_label or 'anonymous'
        return f'{self.action} by {who}'
