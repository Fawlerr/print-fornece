from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, BinaryIO, Generator

from django.conf import settings

from .base import BaseBackupStorageProvider

logger = logging.getLogger(__name__)


class GoogleDriveBackupProvider(BaseBackupStorageProvider):
    """
    Provedor de armazenamento em nuvem via Google Drive API v3.
    
    Para ativar a sincronização automática com o Google Drive:
    1. Crie uma Conta de Serviço (Service Account) no Google Cloud Console com a Google Drive API habilitada.
    2. Baixe o JSON de credenciais e configure a variável de ambiente GOOGLE_DRIVE_CREDENTIALS_JSON ou GOOGLE_DRIVE_CREDENTIALS_PATH.
    3. Crie uma pasta no Google Drive, compartilhe com o e-mail da Service Account (com permissão de Editor) e configure GOOGLE_DRIVE_FOLDER_ID.
    """

    def __init__(
        self,
        folder_id: str | None = None,
        credentials_json: str | None = None,
        credentials_path: str | None = None,
    ) -> None:
        self.folder_id = folder_id or os.getenv("GOOGLE_DRIVE_FOLDER_ID") or getattr(settings, "GOOGLE_DRIVE_FOLDER_ID", "")
        self.credentials_json = credentials_json or os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON") or getattr(settings, "GOOGLE_DRIVE_CREDENTIALS_JSON", "")
        self.credentials_path = credentials_path or os.getenv("GOOGLE_DRIVE_CREDENTIALS_PATH") or getattr(settings, "GOOGLE_DRIVE_CREDENTIALS_PATH", "")

    def is_configured(self) -> bool:
        """Verifica se as credenciais e o ID da pasta do Google Drive foram fornecidos."""
        has_credentials = bool(self.credentials_json.strip() or (self.credentials_path and Path(self.credentials_path).exists()))
        has_folder = bool(self.folder_id.strip())
        return has_credentials and has_folder

    def get_status_info(self) -> dict[str, Any]:
        """Retorna informações de diagnóstico e status de integração."""
        configured = self.is_configured()
        return {
            "name": "Google Drive",
            "is_configured": configured,
            "has_credentials": bool(self.credentials_json.strip() or (self.credentials_path and Path(self.credentials_path).exists())),
            "has_folder_id": bool(self.folder_id.strip()),
            "folder_id": self.folder_id if self.folder_id else None,
            "status_label": "Conectado e Ativo" if configured else "Pronto para conexão (Aguardando Credenciais)",
        }

    def _get_drive_service(self):
        """Inicializa e autentica o cliente da API do Google Drive."""
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError:
            raise ImportError(
                "As bibliotecas 'google-api-python-client' e 'google-auth' são necessárias para integração com o Google Drive."
            )

        scopes = ["https://www.googleapis.com/auth/drive.file"]
        if self.credentials_json.strip():
            cred_dict = json.loads(self.credentials_json)
            credentials = service_account.Credentials.from_service_account_info(cred_dict, scopes=scopes)
        elif self.credentials_path and Path(self.credentials_path).exists():
            credentials = service_account.Credentials.from_service_account_file(self.credentials_path, scopes=scopes)
        else:
            raise ValueError("Credenciais do Google Drive não fornecidas.")

        return build("drive", "v3", credentials=credentials)

    def save(self, file_path: Path, filename: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.is_configured():
            logger.info("Google Drive não configurado. Pulando upload em nuvem.")
            return {
                "storage": "google_drive",
                "configured": False,
                "skipped": True,
                "file_id": "",
            }

        try:
            from googleapiclient.http import MediaFileUpload

            service = self._get_drive_service()
            file_metadata = {
                "name": filename,
                "parents": [self.folder_id] if self.folder_id else [],
                "description": f"Backup Print Fornece gerado em {metadata.get('created_at') if metadata else 'N/D'}",
            }

            mimetype = "application/gzip" if filename.endswith(".gz") else "application/zip"
            media = MediaFileUpload(str(file_path), mimetype=mimetype, resumable=True)

            uploaded_file = (
                service.files()
                .create(body=file_metadata, media_body=media, fields="id, name, webViewLink, size")
                .execute()
            )

            file_id = uploaded_file.get("id", "")
            logger.info(f"Backup {filename} enviado com sucesso para o Google Drive (ID: {file_id})")

            return {
                "storage": "google_drive",
                "configured": True,
                "skipped": False,
                "file_id": file_id,
                "web_view_link": uploaded_file.get("webViewLink", ""),
                "file_size": uploaded_file.get("size", 0),
            }
        except Exception as exc:
            logger.error(f"Erro ao enviar backup para o Google Drive: {exc}", exc_info=True)
            return {
                "storage": "google_drive",
                "configured": True,
                "skipped": False,
                "error": str(exc),
                "file_id": "",
            }

    def delete(self, identifier: str) -> bool:
        if not self.is_configured() or not identifier:
            return False
        try:
            service = self._get_drive_service()
            service.files().delete(fileId=identifier).execute()
            return True
        except Exception as exc:
            logger.error(f"Erro ao excluir arquivo {identifier} do Google Drive: {exc}")
            return False

    def exists(self, identifier: str) -> bool:
        if not self.is_configured() or not identifier:
            return False
        try:
            service = self._get_drive_service()
            service.files().get(fileId=identifier, fields="id").execute()
            return True
        except Exception:
            return False

    def open_stream(self, identifier: str) -> Generator[bytes, None, None] | BinaryIO:
        if not self.is_configured():
            raise RuntimeError("Google Drive não configurado.")
        try:
            import io
            from googleapiclient.http import MediaIoBaseDownload

            service = self._get_drive_service()
            request = service.files().get_media(fileId=identifier)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            return fh
        except Exception as exc:
            raise RuntimeError(f"Erro ao baixar arquivo do Google Drive: {exc}") from exc
