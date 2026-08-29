from __future__ import annotations

import math
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.permissions import DevRequiredMixin
from apps.backups.models import BackupRecord
from apps.backups.services.backup_service import BackupService
from apps.backups.services.providers.google_drive import GoogleDriveBackupProvider
from apps.backups.services.providers.local import LocalBackupProvider


def format_bytes(size_in_bytes: int) -> str:
    if not size_in_bytes or size_in_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(size_in_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_in_bytes / p, 2)
    return f"{s} {units[i]}"


class BackupListView(LoginRequiredMixin, DevRequiredMixin, TemplateView):
    template_name = "backups/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        backups = BackupRecord.objects.select_related("created_by").order_by("-created_at")
        
        total_count = backups.count()
        last_backup = backups.filter(status=BackupRecord.Status.SUCCESS).first()
        total_bytes = backups.filter(status=BackupRecord.Status.SUCCESS).aggregate(total=Sum("file_size"))["total"] or 0
        
        gdrive_provider = GoogleDriveBackupProvider()
        gdrive_status = gdrive_provider.get_status_info()

        context.update({
            "backups": backups[:50],
            "total_count": total_count,
            "last_backup": last_backup,
            "total_disk_usage": format_bytes(total_bytes),
            "gdrive_status": gdrive_status,
        })
        return context


class BackupCreateView(LoginRequiredMixin, DevRequiredMixin, View):
    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponseRedirect:
        backup_type = request.POST.get("backup_type", BackupRecord.BackupType.DATABASE_ONLY)
        if backup_type not in BackupRecord.BackupType.values:
            backup_type = BackupRecord.BackupType.DATABASE_ONLY

        try:
            service = BackupService()
            record = service.create_backup(
                backup_type=backup_type,
                trigger_type=BackupRecord.TriggerType.MANUAL,
                created_by=request.user,
            )
            messages.success(
                request,
                f"Backup '{record.filename}' ({record.formatted_size}) gerado com sucesso! Você já pode baixá-lo.",
            )
        except Exception as exc:
            messages.error(request, f"Erro ao gerar backup: {exc}")

        return redirect("backups:list")


class BackupDownloadView(LoginRequiredMixin, DevRequiredMixin, View):
    def get(self, request: HttpRequest, pk: int, *args, **kwargs) -> HttpResponse:
        record = get_object_or_404(BackupRecord, pk=pk)
        local_provider = LocalBackupProvider()

        if not local_provider.exists(record.file_path):
            messages.error(request, "Arquivo de backup não encontrado no armazenamento local.")
            return redirect("backups:list")

        file_path = Path(record.file_path)
        content_type = "application/gzip" if record.filename.endswith(".gz") else "application/zip"

        response = FileResponse(
            open(file_path, "rb"),
            content_type=content_type,
            as_attachment=True,
            filename=record.filename,
        )
        response["Content-Length"] = record.file_size or file_path.stat().st_size
        return response


class BackupDeleteView(LoginRequiredMixin, DevRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int, *args, **kwargs) -> HttpResponseRedirect:
        record = get_object_or_404(BackupRecord, pk=pk)
        
        # Remove arquivo local se existir
        local_provider = LocalBackupProvider()
        if record.file_path:
            local_provider.delete(record.file_path)

        filename = record.filename
        record.delete()

        messages.success(request, f"Registro de backup '{filename}' excluído com sucesso.")
        return redirect("backups:list")
