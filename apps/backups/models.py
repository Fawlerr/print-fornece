from __future__ import annotations

import math
from django.conf import settings
from django.db import models


class BackupRecord(models.Model):
    class BackupType(models.TextChoices):
        DATABASE_ONLY = "db_only", "Banco de Dados (.sql.gz)"
        FULL_WITH_MEDIA = "full_with_media", "Completo (Banco + Mídias .zip)"

    class TriggerType(models.TextChoices):
        MANUAL = "manual", "Manual (Via Painel)"
        AUTOMATIC = "automatic", "Automático (Rotina Madrugada)"

    class Status(models.TextChoices):
        SUCCESS = "success", "Sucesso"
        FAILED = "failed", "Falha"
        IN_PROGRESS = "in_progress", "Em Execução"

    class StorageLocation(models.TextChoices):
        LOCAL = "local", "Armazenamento Local"
        GOOGLE_DRIVE = "google_drive", "Google Drive"
        LOCAL_AND_DRIVE = "local_and_drive", "Local e Google Drive"

    filename = models.CharField("nome do arquivo", max_length=255)
    file_path = models.CharField("caminho do arquivo", max_length=500)
    file_size = models.BigIntegerField("tamanho em bytes", default=0)
    backup_type = models.CharField(
        "tipo de backup",
        max_length=30,
        choices=BackupType.choices,
        default=BackupType.DATABASE_ONLY,
    )
    trigger_type = models.CharField(
        "origem",
        max_length=30,
        choices=TriggerType.choices,
        default=TriggerType.MANUAL,
    )
    storage_location = models.CharField(
        "local de armazenamento",
        max_length=30,
        choices=StorageLocation.choices,
        default=StorageLocation.LOCAL,
    )
    gdrive_file_id = models.CharField("ID no Google Drive", max_length=255, blank=True)
    checksum_sha256 = models.CharField("hash SHA-256", max_length=64, blank=True)
    status = models.CharField(
        "situação",
        max_length=30,
        choices=Status.choices,
        default=Status.SUCCESS,
        db_index=True,
    )
    error_message = models.TextField("mensagem de erro", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="backups_generated",
        verbose_name="gerado por",
    )
    created_at = models.DateTimeField("data de criação", auto_now_add=True, db_index=True)

    class Meta:
        db_table = "pf_backups"
        ordering = ["-created_at"]
        verbose_name = "Registro de Backup"
        verbose_name_plural = "Registros de Backup"
        indexes = [
            models.Index(fields=["status", "created_at"], name="pf_bkp_status_created"),
            models.Index(fields=["trigger_type", "created_at"], name="pf_bkp_trigger_created"),
        ]

    def __str__(self) -> str:
        return f"{self.filename} ({self.get_status_display()}) - {self.created_at:%d/%m/%Y %H:%M}"

    @property
    def formatted_size(self) -> str:
        """Formata o tamanho do arquivo em formato legível (KB, MB, GB)."""
        if not self.file_size or self.file_size <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.floor(math.log(self.file_size, 1024)))
        p = math.pow(1024, i)
        s = round(self.file_size / p, 2)
        return f"{s} {units[i]}"
