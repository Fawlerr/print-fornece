from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "entity", "entity_id", "user")
    list_filter = ("entity", "action")
    search_fields = ("entity", "entity_id", "user__email")
    readonly_fields = ("user", "action", "entity", "entity_id", "before", "after", "ip", "user_agent", "created_at")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not getattr(request.user, "is_dev", False):
            from apps.accounts.models import User
            dev_ids = list(User.objects.filter(role=User.Role.DEV).values_list("pk", flat=True))
            qs = qs.exclude(user__role=User.Role.DEV).exclude(entity="usuario", entity_id__in=dev_ids)
        return qs

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

