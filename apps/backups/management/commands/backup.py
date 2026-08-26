from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.backups.models import BackupRecord
from apps.backups.services.backup_service import BackupService


class Command(BaseCommand):
    help = "Gera um novo backup do banco de dados (e mídias opcionais) do Print Fornece."

    def add_arguments(self, parser):
        parser.add_argument(
            "--include-media",
            action="store_true",
            help="Inclui os arquivos de upload de mídia no arquivo compactado (.zip).",
        )
        parser.add_argument(
            "--trigger",
            type=str,
            choices=["manual", "automatic"],
            default="automatic",
            help="Identifica a origem do backup (manual ou automático).",
        )
        parser.add_argument(
            "--retention",
            type=int,
            default=30,
            help="Número de dias para manter backups locais antes do expurgo (padrão: 30 dias).",
        )

    def handle(self, *args, **options):
        include_media = options.get("include_media", False)
        trigger = options.get("trigger", "automatic")
        retention = options.get("retention", 30)

        backup_type = (
            BackupRecord.BackupType.FULL_WITH_MEDIA
            if include_media
            else BackupRecord.BackupType.DATABASE_ONLY
        )
        trigger_type = (
            BackupRecord.TriggerType.AUTOMATIC
            if trigger == "automatic"
            else BackupRecord.TriggerType.MANUAL
        )

        self.stdout.write(self.style.NOTICE(f"Iniciando backup [{trigger_type.upper()}] às {timezone.now():%d/%m/%Y %H:%M:%S}..."))

        service = BackupService()
        try:
            record = service.create_backup(
                backup_type=backup_type,
                trigger_type=trigger_type,
                retention_days=retention,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Backup gerado com sucesso!\n"
                    f" - Arquivo: {record.filename}\n"
                    f" - Tamanho: {record.formatted_size}\n"
                    f" - Destino: {record.get_storage_location_display()}\n"
                    f" - SHA-256: {record.checksum_sha256}"
                )
            )
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Erro na execução do backup: {exc}"))
            raise CommandError(f"Falha ao gerar backup: {exc}")
