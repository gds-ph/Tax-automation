from django.contrib import admin

from .models import Agent


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at", "token_rotated_at", "last_seen_at")
    fields = ("id", "name", "is_active", "created_at", "token_rotated_at", "last_seen_at")
    readonly_fields = fields
    actions = None

    # Credential provisioning uses local services for now. No token or hash is
    # shown in admin. Provisioning remains an operator command.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


from .models import PreparationAttempt


@admin.register(PreparationAttempt)
class PreparationAttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "work_order", "agent", "state", "lease_expires_at", "started_at", "completed_at")
    fields = ("id", "work_order", "snapshot", "agent", "state", "lease_expires_at", "started_at", "completed_at")
    readonly_fields = fields
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
