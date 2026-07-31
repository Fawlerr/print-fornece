from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "entity", "entity_id", "user")
    list_filter = ("entity", "action")
    search_fields = ("entity", "entity_id", "user__email")
    readonly_fields = ("user", "action", "entity", "entity_id", "before", "after", "ip", "user_agent", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

