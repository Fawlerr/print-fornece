from __future__ import annotations

import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.orders.legacy_import import LegacyImporter


class Command(BaseCommand):
    help = "Importa o banco PHP legado para o schema Django, sem tocar nas tabelas de origem."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Valida a origem e relata registros sem gravar no Django.")
        parser.add_argument("--confirm-backup", action="store_true", help="Confirma que um backup da origem foi criado.")
        parser.add_argument("--backup-file", help="Caminho para o dump SQL da origem; obrigatório fora do dry-run.")
        parser.add_argument("--upload-root", default=os.getenv("LEGACY_UPLOAD_ROOT", ""), help="Pasta uploads/pedidos da versão PHP.")
        parser.add_argument("--batch-size", type=int, default=250)
        parser.add_argument("--report-file", help="Arquivo JSON do relatório final.")
        parser.add_argument("--source-name", default=os.getenv("LEGACY_MYSQL_DATABASE", ""))
        parser.add_argument("--source-user", default=os.getenv("LEGACY_MYSQL_USER", ""))
        parser.add_argument("--source-password", default=os.getenv("LEGACY_MYSQL_PASSWORD", ""))
        parser.add_argument("--source-host", default=os.getenv("LEGACY_MYSQL_HOST", "127.0.0.1"))
        parser.add_argument("--source-port", type=int, default=int(os.getenv("LEGACY_MYSQL_PORT", "3306")))

    def handle(self, *args, **options):
        if options["batch_size"] < 1:
            raise CommandError("--batch-size deve ser maior que zero.")
        if not options["source_name"] or not options["source_user"]:
            raise CommandError("Informe as credenciais da origem por variáveis LEGACY_MYSQL_* ou argumentos --source-*." )
        destination = settings.DATABASES["default"].get("NAME")
        if options["source_name"] == destination:
            raise CommandError("A origem deve ser um banco separado do novo schema Django; a importação nunca altera o banco PHP original.")
        if not options["dry_run"]:
            backup_file = Path(options.get("backup_file") or "")
            if not options["confirm_backup"] or not backup_file.is_file() or backup_file.stat().st_size == 0:
                raise CommandError("Para gravar, crie um dump SQL da origem e informe --backup-file CAMINHO --confirm-backup.")
        try:
            import MySQLdb
            import MySQLdb.cursors
        except ImportError as exc:
            raise CommandError("mysqlclient não está instalado. Instale requirements.txt no ambiente Python 3.12+.") from exc
        source = MySQLdb.connect(
            host=options["source_host"], user=options["source_user"], passwd=options["source_password"], db=options["source_name"],
            port=options["source_port"], charset="utf8mb4", use_unicode=True, cursorclass=MySQLdb.cursors.DictCursor,
        )
        try:
            importer = LegacyImporter(source, dry_run=options["dry_run"], source_upload_root=options["upload_root"] or None, batch_size=options["batch_size"])
            report = importer.run().as_dict()
        finally:
            source.close()
        rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        self.stdout.write(rendered)
        if options.get("report_file"):
            report_path = Path(options["report_file"])
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(rendered + "\n", encoding="utf-8")

