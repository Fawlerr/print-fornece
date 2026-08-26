from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from apps.backups.models import BackupRecord
from .providers.google_drive import GoogleDriveBackupProvider
from .providers.local import LocalBackupProvider

logger = logging.getLogger(__name__)


class BackupService:
    """Serviço unificado de geração, compressão, persistência e auditoria de backups."""

    def __init__(
        self,
        local_provider: LocalBackupProvider | None = None,
        gdrive_provider: GoogleDriveBackupProvider | None = None,
    ) -> None:
        self.local_provider = local_provider or LocalBackupProvider()
        self.gdrive_provider = gdrive_provider or GoogleDriveBackupProvider()

    def create_backup(
        self,
        backup_type: str = BackupRecord.BackupType.DATABASE_ONLY,
        trigger_type: str = BackupRecord.TriggerType.MANUAL,
        created_by: Any = None,
        retention_days: int | None = None,
    ) -> BackupRecord:
        """Gera um novo backup do sistema, persiste localmente e sincroniza em nuvem se configurado."""
        now = timezone.localtime(timezone.now())
        timestamp_str = now.strftime("%Y-%m-%d_%H%M%S")
        
        # Cria diretório temporário para geração do arquivo
        temp_dir = Path(tempfile.mkdtemp(prefix="pf_backup_"))
        
        try:
            if backup_type == BackupRecord.BackupType.FULL_WITH_MEDIA:
                filename = f"backup_printfornece_completo_{timestamp_str}.zip"
                temp_file = temp_dir / filename
                self._generate_full_zip(temp_file)
            else:
                filename = f"backup_printfornece_db_{timestamp_str}.sql.gz"
                temp_file = temp_dir / filename
                self._generate_database_dump_gzip(temp_file)

            file_size = temp_file.stat().st_size
            checksum = self._calculate_sha256(temp_file)

            # 1. Salvar no Storage Local
            local_info = self.local_provider.save(
                file_path=temp_file,
                filename=filename,
                metadata={"created_at": now.isoformat()},
            )

            storage_location = BackupRecord.StorageLocation.LOCAL
            gdrive_file_id = ""

            # 2. Salvar no Google Drive se estiver configurado
            if self.gdrive_provider.is_configured():
                gdrive_info = self.gdrive_provider.save(
                    file_path=temp_file,
                    filename=filename,
                    metadata={"created_at": now.isoformat(), "size": file_size},
                )
                if gdrive_info.get("file_id"):
                    gdrive_file_id = gdrive_info["file_id"]
                    storage_location = BackupRecord.StorageLocation.LOCAL_AND_DRIVE

            # 3. Registrar auditoria no Banco de Dados
            record = BackupRecord.objects.create(
                filename=filename,
                file_path=local_info["file_path"],
                file_size=file_size,
                backup_type=backup_type,
                trigger_type=trigger_type,
                storage_location=storage_location,
                gdrive_file_id=gdrive_file_id,
                checksum_sha256=checksum,
                status=BackupRecord.Status.SUCCESS,
                created_by=created_by,
            )

            # 4. Executar política de retenção (expurgo de backups antigos)
            days = retention_days if retention_days is not None else getattr(settings, "BACKUP_RETENTION_DAYS", 30)
            self.local_provider.cleanup_old_backups(retention_days=days)

            logger.info(f"Backup concluído com sucesso: {filename} ({record.formatted_size})")
            return record

        except Exception as exc:
            logger.error(f"Falha na geração do backup: {exc}", exc_info=True)
            # Registra o histórico de falha
            record = BackupRecord.objects.create(
                filename=f"backup_falha_{timestamp_str}.err",
                file_path="",
                file_size=0,
                backup_type=backup_type,
                trigger_type=trigger_type,
                storage_location=BackupRecord.StorageLocation.LOCAL,
                status=BackupRecord.Status.FAILED,
                error_message=str(exc),
                created_by=created_by,
            )
            raise exc
        finally:
            shutil.rmtree(str(temp_dir), ignore_errors=True)

    def _generate_database_dump_gzip(self, output_path: Path) -> None:
        """Gera dump do banco de dados e salva diretamente compactado em gzip."""
        db_engine = connection.settings_dict["ENGINE"]
        
        if "mysql" in db_engine or "mariadb" in db_engine:
            self._dump_mysql_gzip(output_path)
        elif "sqlite" in db_engine:
            self._dump_sqlite_gzip(output_path)
        else:
            self._dump_django_json_gzip(output_path)

    def _dump_mysql_gzip(self, output_path: Path) -> None:
        """Gera dump MySQL/MariaDB usando mysqldump/mariadb-dump ou fallback via django dumpdata."""
        db_conf = connection.settings_dict
        db_name = db_conf["NAME"]
        db_user = db_conf["USER"]
        db_password = db_conf["PASSWORD"]
        db_host = db_conf.get("HOST") or "127.0.0.1"
        db_port = str(db_conf.get("PORT") or "3306")

        # Procura por executáveis mysqldump ou mariadb-dump
        dump_cmd_name = shutil.which("mariadb-dump") or shutil.which("mysqldump")

        if dump_cmd_name:
            cmd = [
                dump_cmd_name,
                f"--host={db_host}",
                f"--port={db_port}",
                f"--user={db_user}",
                f"--password={db_password}",
                "--single-transaction",
                "--quick",
                "--routines",
                "--triggers",
                db_name,
            ]
            
            with open(output_path, "wb") as f_out:
                with gzip.GzipFile(filename=output_path.stem, mode="wb", fileobj=f_out, compresslevel=9) as gz_out:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    stdout, stderr = proc.communicate()
                    if proc.returncode != 0:
                        err_msg = stderr.decode("utf-8", errors="replace")
                        logger.warning(f"mysqldump retornou código {proc.returncode}: {err_msg}. Tentando fallback...")
                        self._dump_django_json_gzip(output_path)
                        return
                    gz_out.write(stdout)
        else:
            # Fallback para dump JSON do Django compactado
            logger.info("Executável mysqldump não encontrado no PATH. Usando dump nativo Django.")
            self._dump_django_json_gzip(output_path)

    def _dump_sqlite_gzip(self, output_path: Path) -> None:
        """Gera dump SQL de base SQLite compactado em gzip."""
        db_path = Path(connection.settings_dict["NAME"])
        if not db_path.exists():
            self._dump_django_json_gzip(output_path)
            return

        with open(output_path, "wb") as f_out:
            with gzip.GzipFile(filename=output_path.stem, mode="wb", fileobj=f_out, compresslevel=9) as gz_out:
                con = sqlite3.connect(str(db_path))
                for line in con.iterdump():
                    gz_out.write(f"{line}\n".encode("utf-8"))
                con.close()

    def _dump_django_json_gzip(self, output_path: Path) -> None:
        """Dump fallback usando serialize/dumpdata do Django."""
        buffer = io.StringIO()
        call_command(
            "dumpdata",
            natural_foreign=True,
            natural_primary=True,
            exclude=["contenttypes", "auth.permission"],
            stdout=buffer,
        )
        data = buffer.getvalue().encode("utf-8")
        with open(output_path, "wb") as f_out:
            with gzip.GzipFile(filename=output_path.stem, mode="wb", fileobj=f_out, compresslevel=9) as gz_out:
                gz_out.write(data)

    def _generate_full_zip(self, output_path: Path) -> None:
        """Gera arquivo .zip contendo o dump do banco de dados + diretório de mídias/uploads."""
        temp_sql_gz = output_path.parent / "database.sql.gz"
        self._generate_database_dump_gzip(temp_sql_gz)

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
            # Adiciona o dump do banco de dados
            zipf.write(str(temp_sql_gz), arcname="database.sql.gz")
            
            # Adiciona os arquivos de mídia (uploads)
            media_root = Path(settings.MEDIA_ROOT)
            if media_root.exists() and media_root.is_dir():
                for root, _, files in os.walk(str(media_root)):
                    for file in files:
                        file_full = Path(root) / file
                        rel_path = file_full.relative_to(media_root)
                        zipf.write(str(file_full), arcname=f"media/{rel_path}")

        if temp_sql_gz.exists():
            temp_sql_gz.unlink()

    @staticmethod
    def _calculate_sha256(file_path: Path) -> str:
        """Calcula o hash SHA-256 para integridade do arquivo."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(64 * 1024):
                sha256.update(chunk)
        return sha256.hexdigest()
