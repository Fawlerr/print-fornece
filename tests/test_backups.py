from __future__ import annotations

import gzip
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.models import User
from apps.backups.models import BackupRecord
from apps.backups.services.backup_service import BackupService
from apps.backups.services.providers.google_drive import GoogleDriveBackupProvider
from apps.backups.services.providers.local import LocalBackupProvider


@pytest.fixture
def dev_user(db):
    return User.objects.create_user(
        email="dev@test.com",
        name="Dev Test",
        password="password123",
        role=User.Role.DEV,
    )


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="admin@test.com",
        name="Admin Test",
        password="password123",
        role=User.Role.ADMINISTRATOR,
    )


@pytest.fixture
def employee_user(db):
    return User.objects.create_user(
        email="employee@test.com",
        name="Employee Test",
        password="password123",
        role=User.Role.EMPLOYEE,
    )


@pytest.mark.django_db
def test_backup_service_creates_gzip_file(tmp_path):
    local_provider = LocalBackupProvider(backup_dir=tmp_path)
    service = BackupService(local_provider=local_provider)

    record = service.create_backup(
        backup_type=BackupRecord.BackupType.DATABASE_ONLY,
        trigger_type=BackupRecord.TriggerType.MANUAL,
    )

    assert record.pk is not None
    assert record.status == BackupRecord.Status.SUCCESS
    assert record.filename.endswith(".sql.gz")
    assert record.file_size > 0
    assert len(record.checksum_sha256) == 64

    # Testa se o arquivo gerado é um gzip válido
    backup_file = Path(record.file_path)
    assert backup_file.exists()
    with gzip.open(backup_file, "rb") as gz:
        content = gz.read()
        assert len(content) > 0


@pytest.mark.django_db
def test_backup_management_command(tmp_path, settings):
    settings.BACKUP_ROOT = tmp_path
    call_command("backup", "--trigger=automatic", "--retention=30")

    record = BackupRecord.objects.first()
    assert record is not None
    assert record.trigger_type == BackupRecord.TriggerType.AUTOMATIC
    assert record.status == BackupRecord.Status.SUCCESS


@pytest.mark.django_db
def test_backup_views_access_control(client, dev_user, admin_user, employee_user, tmp_path, settings):
    settings.BACKUP_ROOT = tmp_path
    url = reverse("backups:list")

    # 1. Usuário não autenticado -> redireciona para login
    resp = client.get(url)
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url

    # 2. Funcionário -> 403 Proibido
    client.force_login(employee_user)
    resp = client.get(url)
    assert resp.status_code == 403

    # 3. Administrador comum (não-dev) -> 403 Proibido
    client.force_login(admin_user)
    resp = client.get(url)
    assert resp.status_code == 403

    # 4. Desenvolvedor -> 200 OK
    client.force_login(dev_user)
    resp = client.get(url)
    assert resp.status_code == 200
    assert "Gestão de Backups" in resp.content.decode("utf-8")


@pytest.mark.django_db
def test_backup_download_view(client, dev_user, tmp_path):
    local_provider = LocalBackupProvider(backup_dir=tmp_path)
    service = BackupService(local_provider=local_provider)
    record = service.create_backup(backup_type=BackupRecord.BackupType.DATABASE_ONLY)

    client.force_login(dev_user)
    download_url = reverse("backups:download", kwargs={"pk": record.pk})
    resp = client.get(download_url)

    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/gzip"
    assert record.filename in resp["Content-Disposition"]


@pytest.mark.django_db
def test_backup_delete_view(client, dev_user, tmp_path):
    local_provider = LocalBackupProvider(backup_dir=tmp_path)
    service = BackupService(local_provider=local_provider)
    record = service.create_backup(backup_type=BackupRecord.BackupType.DATABASE_ONLY)

    file_path = Path(record.file_path)
    assert file_path.exists()

    client.force_login(dev_user)
    delete_url = reverse("backups:delete", kwargs={"pk": record.pk})
    resp = client.post(delete_url)

    assert resp.status_code == 302
    assert not file_path.exists()
    assert not BackupRecord.objects.filter(pk=record.pk).exists()


def test_google_drive_provider_unconfigured():
    provider = GoogleDriveBackupProvider(folder_id="", credentials_json="")
    assert not provider.is_configured()
    info = provider.get_status_info()
    assert not info["is_configured"]
    assert "Aguardando" in info["status_label"]

    # Tentativa de save quando não configurado não deve lançar erro fatal
    result = provider.save(Path("fake.sql.gz"), "fake.sql.gz")
    assert result["skipped"] is True
