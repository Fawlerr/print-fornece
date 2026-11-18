"""Confere (e com --aplicar, corrige) o webhook das instâncias ativas da Evolution.

Na Umbler Talk o webhook é cadastrado no painel (Configurações > Webhooks); a URL aparece em Números conectados.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.whatsapp.evolution import EVENTOS_WEBHOOK, EvolutionClient, EvolutionErro, url_webhook
from apps.whatsapp.models import Instancia


class Command(BaseCommand):
    help = "Confere o webhook das instâncias de WhatsApp na Evolution API."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true", help="Configura URL e eventos nas instâncias divergentes.")

    def handle(self, *args, aplicar: bool, **options):
        cliente = EvolutionClient()
        try:
            esperado = url_webhook()
        except EvolutionErro as exc:
            self.stderr.write(str(exc))
            return
        for inst in Instancia.objects.filter(ativa=True, provedor=Instancia.Provedor.EVOLUTION):
            try:
                atual = cliente.consultar_webhook(inst.nome)
            except EvolutionErro as exc:
                self.stderr.write(f"{inst.nome}: {exc}")
                continue
            eventos = {str(e).upper().replace(".", "_") for e in (atual.get("events") or [])}
            ok = atual.get("url") == esperado and bool(atual.get("enabled", True)) and set(EVENTOS_WEBHOOK) <= eventos
            # Nunca imprime a URL completa: ela contém o segredo do webhook.
            self.stdout.write(f"{inst.nome}: {'OK' if ok else 'DIVERGENTE'}")
            if not ok and aplicar:
                res = cliente.configurar_webhook(inst.nome)
                self.stdout.write(f"  -> {'corrigido' if res.ok else 'falhou (' + res.erro + ')'}")
