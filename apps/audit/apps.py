from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.audit'
    verbose_name = 'Audit log'

    def ready(self):
        import apps.audit.signals  # noqa: F401 — registers the auth signal receivers
