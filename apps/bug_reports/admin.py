from django.contrib import admin

from .models import BugReport


@admin.register(BugReport)
class BugReportAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "current_url", "created_at", "resolved_at")
    list_filter = ("status", "created_at", "resolved_at")
    search_fields = ("user__name", "user__email", "description", "current_url", "dev_notes")
    readonly_fields = ("created_at", "updated_at")
