"""Atualiza entregue/lida/falhou das mensagens enviadas pela Umbler Talk.

A Umbler ainda não manda webhook de status ("Ainda não temos eventos para atualizações de status"), então
o estado é consultado em GET /v1/messages/{id}/. Agende no cron a cada 1–2 minutos:
    python manage.py whatsapp_atualizar_status
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.whatsapp.services import atualizar_status_enviadas


class Command(BaseCommand):
    help = "Consulta na Umbler o status das mensagens enviadas recentemente."

    def add_arguments(self, parser):
        parser.add_argument("--horas", type=int, default=24, help="Janela de mensagens a conferir (padrão: 24 h).")
        parser.add_argument("--limite", type=int, default=200, help="Máximo de mensagens por execução (padrão: 200).")

    def handle(self, *args, horas: int, limite: int, **options):
        resumo = atualizar_status_enviadas(horas=horas, limite=limite)
        self.stdout.write(self.style.SUCCESS("Status atualizado: " + (", ".join(f"{k}={v}" for k, v in sorted(resumo.items())) or "nada a conferir")))
