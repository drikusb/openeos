from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Read-only view of every organisation's audit events."""

    list_display = ['action', 'actor_label', 'organization', 'created_at']
    list_filter = ['action', 'created_at']
    search_fields = ['actor_label', 'target_label', 'action']
    date_hierarchy = 'created_at'
    list_select_related = ['organization']
    readonly_fields = [
        'organization', 'actor', 'actor_label', 'action', 'target_type', 'target_id',
        'target_label', 'details', 'ip_address', 'user_agent', 'created_at',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
