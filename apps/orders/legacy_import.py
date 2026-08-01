"""Idempotent, non-destructive importer for the original PHP/MySQL schema."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable

from django.core.files import File
from django.db import connection, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.expenses.models import Expense
from apps.notifications.models import Notification
from apps.payments.models import Charge

from .models import Order, OrderAttachment, OrderHistory, OrderNote, OrderStageHistory


@dataclass
class MigrationReport:
    dry_run: bool
    imported: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    rejected: list[dict[str, str]] = field(default_factory=list)
    missing_files: list[dict[str, str]] = field(default_factory=list)

    def mark(self, table: str, created: bool) -> None:
        target = self.imported if created else self.updated
        target[table] = target.get(table, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def legacy_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


def legacy_json(value):
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {"legacy_unparsed": str(value)}


def as_decimal(value) -> Decimal:
    return Decimal(str(value if value is not None else "0"))


def legacy_link(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith("producao/detalhes.php?id="):
        return f"/production/{value.rsplit('=', 1)[-1]}/"
    if value == "notificacoes/index.php":
        return "/notifications/"
    return value if value.startswith("/") else f"/{value}"


class LegacyImporter:
    """Import source rows in dependency order into the *new* Django schema."""

    tables = (
        "usuarios", "pedidos", "pedido_arquivos", "pedido_historico", "pedido_observacoes",
        "pedido_etapas_historico", "despesas", "notificacoes", "cobrancas", "auditoria",
    )

    def __init__(self, source_connection, *, dry_run: bool, source_upload_root: str | Path | None = None, batch_size: int = 250):
        self.source = source_connection
        self.dry_run = dry_run
        self.source_upload_root = Path(source_upload_root) if source_upload_root else None
        self.batch_size = batch_size
        self.report = MigrationReport(dry_run=dry_run)

    def source_tables(self) -> set[str]:
        cursor = self.source.cursor()
        cursor.execute("SHOW TABLES")
        return {next(iter(row.values())) if isinstance(row, dict) else row[0] for row in cursor.fetchall()}

    def run(self) -> MigrationReport:
        available = self.source_tables()
        for table in self.tables:
            if table not in available:
                continue
            handler = getattr(self, f"import_{table}")
            self._iterate(table, handler)
        if not self.dry_run:
            self._reset_sequences()
        return self.report

    def _iterate(self, table: str, handler: Callable[[dict[str, Any]], bool]) -> None:
        cursor = self.source.cursor()
        cursor.execute(f"SELECT * FROM `{table}` ORDER BY id")
        while rows := cursor.fetchmany(self.batch_size):
            if self.dry_run:
                for row in rows:
                    try:
                        handler(row)
                        self.report.mark(table, True)
                    except Exception as exc:  # A dry run reports bad rows without mutation.
                        self.report.rejected.append({"table": table, "id": str(row.get("id", "?")), "reason": str(exc)})
                continue
            with transaction.atomic():
                for row in rows:
                    try:
                        created = handler(row)
                        self.report.mark(table, created)
                    except Exception as exc:
                        self.report.rejected.append({"table": table, "id": str(row.get("id", "?")), "reason": str(exc)})

    @staticmethod
    def _timestamps(
        model,
        pk: int,
        row: dict[str, Any],
        *,
        created="created_at",
        updated="updated_at",
        source_created="created_at",
        source_updated="updated_at",
    ) -> None:
        values = {}
        if row.get(source_created):
            values[created] = legacy_datetime(row[source_created])
        if source_updated in row and row.get(source_updated) and updated != "__missing__":
            values[updated] = legacy_datetime(row[source_updated])
        if values:
            model.objects.filter(pk=pk).update(**values)

    def _save(self, model, *, pk: int, defaults: dict[str, Any], legacy_row: dict[str, Any], timestamps: bool = True) -> bool:
        if self.dry_run:
            return not model.objects.filter(pk=pk).exists()
        instance, created = model.objects.update_or_create(pk=pk, defaults=defaults)
        if timestamps:
            self._timestamps(model, instance.pk, legacy_row)
        return created

    def import_usuarios(self, row: dict[str, Any]) -> bool:
        legacy_hash = str(row.get("senha") or "")
        password = f"php_bcrypt${legacy_hash}" if legacy_hash.startswith("$2") else None
        defaults = {
            "name": row["nome"], "email": row["email"].lower(),
            "role": row.get("perfil") or User.Role.EMPLOYEE,
            "is_active": bool(row.get("ativo", 1)),
            "is_staff": (row.get("perfil") == User.Role.ADMINISTRATOR),
            "force_password_change": bool(row.get("forcar_troca_senha", 0)),
            "last_login": legacy_datetime(row.get("ultimo_acesso")),
        }
        if self.dry_run:
            return not User.objects.filter(pk=row["id"]).exists()
        user, created = User.objects.update_or_create(pk=row["id"], defaults=defaults)
        # Do not overwrite a post-migration PBKDF2 password on a repeated import.
        if created and password:
            user.password = password
            user.save(update_fields=["password"])
        self._timestamps(User, user.pk, row, created="date_joined", updated="updated_at")
        return created

    def import_pedidos(self, row: dict[str, Any]) -> bool:
        return self._save(Order, pk=row["id"], legacy_row=row, defaults={
            "number": row["numero"], "client_name": row["cliente_nome"], "client_whatsapp": row["cliente_whatsapp"],
            "description": row["descricao"], "total_amount": as_decimal(row["valor_total"]),
            "payment_status": row["status_pagamento"], "paid_amount": as_decimal(row["valor_pago"]),
            "payment_method": row.get("forma_pagamento"), "due_at": legacy_datetime(row.get("previsao_entrega")),
            "priority": row["prioridade"], "internal_notes": row.get("observacoes_internas") or "", "stage": row["etapa"],
            "responsible_id": row.get("responsavel_id"), "created_by_id": row["criado_por_id"],
            "stage_updated_at": legacy_datetime(row.get("etapa_atualizada_em")) or timezone.now(),
            "finished_at": legacy_datetime(row.get("finalizado_em")), "cancelled_at": legacy_datetime(row.get("cancelado_em")),
            "cancelled_by_id": row.get("cancelado_por_id"),
        })

    def import_pedido_arquivos(self, row: dict[str, Any]) -> bool:
        if self.dry_run:
            return not OrderAttachment.objects.filter(pk=row["id"]).exists()
        existing = OrderAttachment.objects.filter(pk=row["id"]).first()
        defaults = {
            "order_id": row["pedido_id"], "original_name": row["nome_original"], "content_type": row["mime_type"],
            "size": row["tamanho"], "created_by_id": row["criado_por_id"], "removed_at": legacy_datetime(row.get("removido_em")),
            "removed_by_id": row.get("removido_por_id"),
        }
        attachment, created = OrderAttachment.objects.update_or_create(pk=row["id"], defaults=defaults)
        self._timestamps(OrderAttachment, attachment.pk, row, updated="__missing__")
        stored_name = row.get("nome_armazenado")
        if not attachment.file and stored_name and self.source_upload_root:
            source_file = self.source_upload_root / Path(stored_name).name
            if source_file.is_file():
                with source_file.open("rb") as handle:
                    attachment.file.save(attachment.original_name, File(handle), save=True)
            else:
                self.report.missing_files.append({"attachment_id": str(row["id"]), "source": str(source_file)})
        return created

    def import_pedido_historico(self, row: dict[str, Any]) -> bool:
        return self._save(OrderHistory, pk=row["id"], legacy_row=row, defaults={
            "order_id": row["pedido_id"], "user_id": row.get("usuario_id"), "action": row["acao"], "description": row["descricao"],
        }, timestamps=True)

    def import_pedido_observacoes(self, row: dict[str, Any]) -> bool:
        return self._save(OrderNote, pk=row["id"], legacy_row=row, defaults={
            "order_id": row["pedido_id"], "user_id": row["usuario_id"], "text": row["texto"],
        }, timestamps=True)

    def import_pedido_etapas_historico(self, row: dict[str, Any]) -> bool:
        return self._save(OrderStageHistory, pk=row["id"], legacy_row=row, defaults={
            "order_id": row["pedido_id"], "previous_stage": row.get("etapa_anterior"), "new_stage": row["etapa_nova"], "user_id": row.get("usuario_id"),
        }, timestamps=True)

    def import_despesas(self, row: dict[str, Any]) -> bool:
        return self._save(Expense, pk=row["id"], legacy_row=row, defaults={
            "description": row["descricao"], "category": row["categoria"], "amount": as_decimal(row["valor"]),
            "expense_date": row["data_despesa"], "note": row.get("observacao") or "", "status": row["status"],
            "created_by_id": row["criado_por_id"], "cancelled_by_id": row.get("cancelado_por_id"),
            "cancelled_at": legacy_datetime(row.get("cancelado_em")),
        })

    def import_notificacoes(self, row: dict[str, Any]) -> bool:
        return self._save(Notification, pk=row["id"], legacy_row=row, defaults={
            "user_id": row["usuario_id"], "title": row["titulo"], "message": row["mensagem"],
            "link": legacy_link(row.get("link")), "type": row["tipo"], "read_at": legacy_datetime(row.get("lida_em")),
        })

    def import_cobrancas(self, row: dict[str, Any]) -> bool:
        return self._save(Charge, pk=row["id"], legacy_row=row, defaults={
            "order_id": row["pedido_id"], "provider": row["provedor"], "type": row["tipo"],
            "external_identifier": row.get("identificador_externo"), "amount": as_decimal(row["valor"]), "status": row["status"],
            "pix_copy_paste": row.get("pix_copia_cola") or "", "checkout_url": row.get("checkout_url") or "",
        })

    def import_auditoria(self, row: dict[str, Any]) -> bool:
        return self._save(AuditEvent, pk=row["id"], legacy_row=row, defaults={
            "user_id": row.get("usuario_id"), "action": row["acao"], "entity": row["entidade"], "entity_id": row.get("entidade_id"),
            "before": legacy_json(row.get("dados_anteriores")), "after": legacy_json(row.get("dados_posteriores")),
            "ip": row.get("ip"), "user_agent": row.get("user_agent") or "",
        })

    def _reset_sequences(self) -> None:
        if connection.vendor != "mysql":
            return
        tables = [
            User._meta.db_table, Order._meta.db_table, OrderAttachment._meta.db_table, OrderHistory._meta.db_table,
            OrderNote._meta.db_table, OrderStageHistory._meta.db_table, Expense._meta.db_table, Notification._meta.db_table,
            Charge._meta.db_table, AuditEvent._meta.db_table,
        ]
        with connection.cursor() as cursor:
            for table in tables:
                cursor.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM `{table}`")
                next_id = int(cursor.fetchone()[0])
                cursor.execute(f"ALTER TABLE `{table}` AUTO_INCREMENT = %s", [next_id])
