from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand, CommandError

from apps.audit.models import AuditEvent
from apps.expenses.models import Expense
from apps.notifications.models import Notification
from apps.payments.models import Charge
from apps.accounts.models import User
from apps.orders.models import Order, OrderAttachment, OrderHistory, OrderNote, OrderStageHistory


class Command(BaseCommand):
    help = "Compara contagens do MySQL legado com o novo schema Django, sem escrever em nenhum banco."

    table_models = {
        "usuarios": User, "pedidos": Order, "pedido_arquivos": OrderAttachment, "pedido_historico": OrderHistory,
        "pedido_observacoes": OrderNote, "pedido_etapas_historico": OrderStageHistory, "despesas": Expense,
        "notificacoes": Notification, "cobrancas": Charge, "auditoria": AuditEvent,
    }

    def add_arguments(self, parser):
        parser.add_argument("--source-name", default=os.getenv("LEGACY_MYSQL_DATABASE", ""))
        parser.add_argument("--source-user", default=os.getenv("LEGACY_MYSQL_USER", ""))
        parser.add_argument("--source-password", default=os.getenv("LEGACY_MYSQL_PASSWORD", ""))
        parser.add_argument("--source-host", default=os.getenv("LEGACY_MYSQL_HOST", "127.0.0.1"))
        parser.add_argument("--source-port", type=int, default=int(os.getenv("LEGACY_MYSQL_PORT", "3306")))

    def handle(self, *args, **options):
        if not options["source_name"] or not options["source_user"]:
            raise CommandError("Informe LEGACY_MYSQL_NAME/USER ou os argumentos --source-*." )
        try:
            import MySQLdb
            import MySQLdb.cursors
        except ImportError as exc:
            raise CommandError("mysqlclient não está instalado.") from exc
        source = MySQLdb.connect(host=options["source_host"], user=options["source_user"], passwd=options["source_password"], db=options["source_name"], port=options["source_port"], cursorclass=MySQLdb.cursors.DictCursor)
        try:
            cursor = source.cursor()
            result = {"matches": True, "tables": {}}
            for legacy_name, model in self.table_models.items():
                cursor.execute("SHOW TABLES LIKE %s", [legacy_name])
                if not cursor.fetchone():
                    continue
                cursor.execute(f"SELECT COUNT(*) AS total FROM `{legacy_name}`")
                legacy_count = int(cursor.fetchone()["total"])
                django_count = model.objects.count()
                matches = legacy_count == django_count
                result["matches"] = result["matches"] and matches
                result["tables"][legacy_name] = {"legacy": legacy_count, "django": django_count, "matches": matches}
        finally:
            source.close()
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["matches"]:
            raise CommandError("As contagens não coincidem; consulte o relatório de migração antes de liberar o sistema.")

