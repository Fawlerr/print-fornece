from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, BinaryIO, Generator


class BaseBackupStorageProvider(ABC):
    """Interface abstrata para provedores de armazenamento de backups."""

    @abstractmethod
    def save(self, file_path: Path, filename: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Salva o arquivo de backup no destino e retorna metadados com ID/caminho."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, identifier: str) -> bool:
        """Remove o backup do destino de armazenamento."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, identifier: str) -> bool:
        """Verifica se o backup existe no destino."""
        raise NotImplementedError

    @abstractmethod
    def open_stream(self, identifier: str) -> Generator[bytes, None, None] | BinaryIO:
        """Abre stream de leitura do arquivo de backup para download."""
        raise NotImplementedError
