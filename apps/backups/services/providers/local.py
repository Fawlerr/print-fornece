from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Generator

from django.conf import settings

from .base import BaseBackupStorageProvider


class LocalBackupProvider(BaseBackupStorageProvider):
    """Provedor de armazenamento em disco local / volume persistente."""

    def __init__(self, backup_dir: Path | None = None) -> None:
        self.backup_dir = backup_dir or getattr(settings, "BACKUP_ROOT", settings.BASE_DIR / "backups")
        self.backup_dir = Path(self.backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def save(self, file_path: Path, filename: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        dest_path = self.backup_dir / filename
        if file_path.resolve() != dest_path.resolve():
            shutil.copy2(str(file_path), str(dest_path))
        file_size = dest_path.stat().st_size
        return {
            "storage": "local",
            "file_path": str(dest_path),
            "filename": filename,
            "file_size": file_size,
        }

    def delete(self, identifier: str) -> bool:
        path = Path(identifier)
        if not path.is_absolute():
            path = self.backup_dir / identifier
        if path.exists() and path.is_file():
            try:
                path.unlink()
                return True
            except OSError:
                return False
        return False

    def exists(self, identifier: str) -> bool:
        path = Path(identifier)
        if not path.is_absolute():
            path = self.backup_dir / identifier
        return path.exists() and path.is_file()

    def open_stream(self, identifier: str) -> Generator[bytes, None, None]:
        path = Path(identifier)
        if not path.is_absolute():
            path = self.backup_dir / identifier
        with open(path, "rb") as f:
            while chunk := f.read(64 * 1024):
                yield chunk

    def cleanup_old_backups(self, retention_days: int = 30) -> list[str]:
        """Remove arquivos de backup mais antigos que o período de retenção."""
        removed: list[str] = []
        if retention_days <= 0:
            return removed
        cutoff_seconds = time.time() - (retention_days * 86400)
        for item in self.backup_dir.glob("backup_*"):
            if item.is_file() and item.stat().st_mtime < cutoff_seconds:
                try:
                    item.unlink()
                    removed.append(item.name)
                except OSError:
                    pass
        return removed
