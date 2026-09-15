from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "work_order", "client", "agent", "actor", "performed_by_agent", "old_status", "new_status")
    list_filter = ("kind", "created_at")
    readonly_fields = tuple(field.name for field in AuditEvent._meta.fields)
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
