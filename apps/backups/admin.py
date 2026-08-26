from django.contrib import admin
from .models import BackupRecord


@admin.register(BackupRecord)
class BackupRecordAdmin(admin.ModelAdmin):
    list_display = ("filename", "backup_type", "trigger_type", "formatted_size", "status", "created_by", "created_at")
    list_filter = ("status", "backup_type", "trigger_type", "storage_location", "created_at")
    search_fields = ("filename", "gdrive_file_id", "error_message")
    readonly_fields = ("created_at", "checksum_sha256", "file_size", "formatted_size")
